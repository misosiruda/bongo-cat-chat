// Read-only, bounded memory pattern search. No game code loading or invocation.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

public sealed class ScanRequest {
    public int pid { get; set; }
    public bool private_only { get; set; }
    public bool pointer_aligned { get; set; }
    public Dictionary<string, string> patterns { get; set; }
}

public static class MemoryScan {
    const int Chunk = 4 * 1024 * 1024;
    [StructLayout(LayoutKind.Sequential)]
    struct Region {
        public IntPtr BaseAddress, AllocationBase;
        public uint AllocationProtect;
        public ushort PartitionId;
        public UIntPtr RegionSize;
        public uint State, Protect, Type;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr process, IntPtr address, [Out] byte[] buffer, UIntPtr size, out UIntPtr read);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern UIntPtr VirtualQueryEx(IntPtr process, IntPtr address, out Region region, UIntPtr size);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr handle);

    public sealed class Matcher {
        readonly Dictionary<string, byte[]> patterns;
        readonly Dictionary<ulong, List<string>> pointers;
        readonly Dictionary<string, int[]> skips = new Dictionary<string, int[]>();
        public readonly Dictionary<string, HashSet<ulong>> Hits = new Dictionary<string, HashSet<ulong>>();
        public int Overlap { get; private set; }

        public Matcher(Dictionary<string, byte[]> values, bool aligned) {
            if (values == null || values.Count == 0 || values.Count > 500) throw new Exception("unsupported_metadata_candidates");
            patterns = values;
            if (aligned) pointers = new Dictionary<ulong, List<string>>();
            foreach (var pair in patterns) {
                var pattern = pair.Value;
                if (pattern.Length == 0 || pattern.Length > 256 || pair.Key.Length > 80) throw new Exception("unsupported_metadata_candidates");
                Overlap = Math.Max(Overlap, pattern.Length);
                Hits[pair.Key] = new HashSet<ulong>();
                if (aligned) {
                    if (pattern.Length != 8) throw new Exception("unsupported_pointer_pattern");
                    ulong value = BitConverter.ToUInt64(pattern, 0);
                    if (!pointers.ContainsKey(value)) pointers[value] = new List<string>();
                    pointers[value].Add(pair.Key);
                } else {
                    var table = new int[256];
                    for (int i = 0; i < table.Length; i++) table[i] = pattern.Length;
                    for (int i = 0; i < pattern.Length - 1; i++) table[pattern[i]] = pattern.Length - 1 - i;
                    skips[pair.Key] = table;
                }
            }
        }

        void Add(string key, ulong address) {
            Hits[key].Add(address);
            if (Hits[key].Count > 4096) throw new Exception("ambiguous_metadata");
        }

        public unsafe void Search(byte[] buffer, int length, ulong start) {
            if (length < 0 || length > buffer.Length) throw new Exception("memory_read_failed");
            if (pointers != null) {
                fixed (byte* bytes = buffer) {
                    int skip = (int)((8 - start % 8) % 8);
                    for (int pos = skip; pos <= length - 8; pos += 8) {
                        List<string> keys;
                        if (pointers.TryGetValue(*(ulong*)(bytes + pos), out keys))
                            foreach (var key in keys) Add(key, start + (ulong)pos);
                    }
                }
            } else {
                foreach (var pair in patterns) {
                    var pattern = pair.Value;
                    var table = skips[pair.Key];
                    int last = pattern.Length - 1, pos = 0;
                    while (pos <= length - pattern.Length) {
                        int index = last;
                        while (index >= 0 && buffer[pos + index] == pattern[index]) index--;
                        if (index < 0) {
                            Add(pair.Key, start + (ulong)pos);
                            pos++; // Preserve overlapping occurrences.
                        } else pos += table[buffer[pos + last]];
                    }
                }
            }
        }
    }

    static object Scan(ScanRequest request) {
        if (request == null || request.pid <= 0 || request.patterns == null) throw new Exception("invalid_scan_request");
        var patterns = new Dictionary<string, byte[]>();
        foreach (var pair in request.patterns) patterns[pair.Key] = Convert.FromBase64String(pair.Value);
        var matcher = new Matcher(patterns, request.pointer_aligned);
        IntPtr handle = OpenProcess(0x0400 | 0x0010, false, request.pid);
        if (handle == IntPtr.Zero) throw new Exception("process_read_denied");
        try {
            var buffer = new byte[Chunk + matcher.Overlap];
            var watch = Stopwatch.StartNew();
            ulong address = 0, total = 0;
            while (address < 0x7fffffffffffUL) {
                if (watch.Elapsed.TotalSeconds > 120 || total > 4UL * 1024 * 1024 * 1024) throw new Exception("discovery_cancelled_or_budget");
                Region region;
                if (VirtualQueryEx(handle, (IntPtr)address, out region, (UIntPtr)Marshal.SizeOf(typeof(Region))) == UIntPtr.Zero) break;
                ulong start = (ulong)region.BaseAddress.ToInt64(), size = region.RegionSize.ToUInt64(), next = start + size;
                if (next <= address) break;
                if (region.State == 0x1000 && (!request.private_only || region.Type == 0x20000) && (region.Protect & (0x100 | 1)) == 0) {
                    for (ulong offset = 0; offset < size; offset += Chunk) {
                        if (watch.Elapsed.TotalSeconds > 120 || total > 4UL * 1024 * 1024 * 1024) throw new Exception("discovery_cancelled_or_budget");
                        int count = (int)Math.Min((ulong)buffer.Length, size - offset);
                        UIntPtr read;
                        ReadProcessMemory(handle, (IntPtr)(start + offset), buffer, (UIntPtr)count, out read);
                        ulong received = read.ToUInt64();
                        if (received > (ulong)count) throw new Exception("memory_read_failed");
                        total += received;
                        matcher.Search(buffer, (int)received, start + offset);
                    }
                }
                address = next;
            }
            return matcher.Hits;
        } finally { CloseHandle(handle); }
    }

    public static int Main() {
        var json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
        try {
            // Bound stdin even when invoked outside the application.
            var input = new char[65537];
            int length = 0, count;
            while (length < input.Length && (count = Console.In.Read(input, length, input.Length - length)) > 0) length += count;
            if (length > 65536) throw new Exception("invalid_scan_request");
            Console.Write(json.Serialize(Scan(json.Deserialize<ScanRequest>(new string(input, 0, length)))));
            return 0;
        } catch (Exception error) {
            string code = error.Message;
            var known = new HashSet<string> {"unsupported_metadata_candidates", "unsupported_pointer_pattern", "ambiguous_metadata",
                "discovery_cancelled_or_budget", "process_read_denied", "memory_read_failed", "invalid_scan_request"};
            Console.Write(json.Serialize(new { error = known.Contains(code) ? code : "memory_scan_failed" }));
            return 2;
        }
    }
}
