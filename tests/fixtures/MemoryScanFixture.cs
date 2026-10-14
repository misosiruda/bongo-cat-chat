// Synthetic buffers only. Exercise the exact compiled matcher, no process reads.
using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;

public sealed class Block {
    public ulong start { get; set; }
    public string data { get; set; }
    public int length { get; set; }
}
public sealed class Fixture {
    public bool aligned { get; set; }
    public Dictionary<string, string> patterns { get; set; }
    public Block[] blocks { get; set; }
}
public static class MemoryScanFixture {
    public static int Main() {
        var json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
        try {
            var fixture = json.Deserialize<Fixture>(Console.In.ReadToEnd());
            var patterns = new Dictionary<string, byte[]>();
            foreach (var pair in fixture.patterns) patterns[pair.Key] = Convert.FromBase64String(pair.Value);
            var matcher = new MemoryScan.Matcher(patterns, fixture.aligned);
            foreach (var block in fixture.blocks) matcher.Search(Convert.FromBase64String(block.data), block.length, block.start);
            Console.Write(json.Serialize(matcher.Hits));
            return 0;
        } catch (Exception error) {
            Console.Write(json.Serialize(new { error = error.Message }));
            return 2;
        }
    }
}
