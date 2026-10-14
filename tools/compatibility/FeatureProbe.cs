// Reads ECMA metadata only. Never loads or invokes game assemblies.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Mono.Cecil;
using Mono.Cecil.Cil;

public sealed class FeatureSpec {
    public string[] methods { get; set; }
    public string[] fields { get; set; }
    public string[] packets { get; set; }
    public string[] writers { get; set; }
    public string route { get; set; }
    public int channel { get; set; }
}
public sealed class ProbeSpec {
    public int schema { get; set; }
    public string[] assemblies { get; set; }
    public Dictionary<string, FeatureSpec> features { get; set; }
}

sealed class Modules : IAssemblyResolver, IDisposable {
    internal readonly Dictionary<string, AssemblyDefinition> assemblies = new Dictionary<string, AssemblyDefinition>(StringComparer.Ordinal);
    internal readonly Dictionary<string, TypeDefinition> types = new Dictionary<string, TypeDefinition>(StringComparer.Ordinal);
    internal Modules(string root, string[] names) {
        if (names == null || names.Length < 1 || names.Length > 8) throw new InvalidDataException();
        foreach (string name in names) {
            if (Path.GetFileName(name) != name || !name.EndsWith(".dll", StringComparison.Ordinal)) throw new InvalidDataException();
            string path = Path.Combine(root, name);
            if (new FileInfo(path).Length > 64 * 1024 * 1024) throw new InvalidDataException();
            var assembly = AssemblyDefinition.ReadAssembly(path, new ReaderParameters { AssemblyResolver = this, InMemory = true, ReadingMode = ReadingMode.Deferred });
            if (assembly.Name.Name + ".dll" != name || assembly.Modules.Count != 1) throw new InvalidDataException();
            assemblies.Add(assembly.Name.Name, assembly);
            foreach (var type in assembly.MainModule.GetTypes()) {
                if (types.Count > 30000) throw new InvalidDataException();
                types.Add(assembly.Name.Name + "|" + type.FullName, type);
            }
        }
    }
    public AssemblyDefinition Resolve(AssemblyNameReference name) { return Resolve(name, null); }
    public AssemblyDefinition Resolve(AssemblyNameReference name, ReaderParameters parameters) {
        AssemblyDefinition assembly;
        if (!assemblies.TryGetValue(name.Name, out assembly)) throw new InvalidDataException("external_resolution");
        return assembly;
    }
    internal static string Scope(TypeReference type) {
        type = type.GetElementType();
        var assembly = type.Scope as AssemblyNameReference;
        var module = type.Scope as ModuleDefinition;
        if (assembly != null) return assembly.Name;
        if (module != null) return module.Assembly.Name.Name;
        throw new InvalidDataException("type_scope");
    }
    internal static string TypeName(TypeReference type) {
        if (type == null) return "";
        if (type is GenericParameter) return type.FullName;
        return Scope(type) + "|" + type.FullName;
    }
    internal TypeDefinition FindType(string key) { return types[key]; }
    internal MethodDefinition FindMethod(string key) {
        int split = key.LastIndexOf('|');
        var rows = FindType(key.Substring(0, split)).Methods.Where(m => m.Name == key.Substring(split + 1)).ToArray();
        // Roots name every overload; adding or removing one changes the contract.
        if (rows.Length != 1) throw new InvalidDataException("ambiguous_method");
        return rows[0];
    }
    internal IEnumerable<MethodDefinition> FindMethods(string key) {
        int split = key.LastIndexOf('|');
        var rows = FindType(key.Substring(0, split)).Methods.Where(m => m.Name == key.Substring(split + 1)).ToArray();
        if (rows.Length == 0 || rows.Length > 32) throw new InvalidDataException("missing_method");
        return rows;
    }
    internal FieldDefinition FindField(string key) {
        int split = key.LastIndexOf('|');
        return FindType(key.Substring(0, split)).Fields.Single(f => f.Name == key.Substring(split + 1));
    }
    public void Dispose() { foreach (var assembly in assemblies.Values) assembly.Dispose(); }
}

sealed class Feature {
    readonly Modules modules;
    readonly SortedDictionary<string, string> records = new SortedDictionary<string, string>(StringComparer.Ordinal);
    readonly Queue<MethodDefinition> pending = new Queue<MethodDefinition>();
    readonly HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    int instructions;
    internal Feature(Modules modules) { this.modules = modules; }
    static string MethodKey(MethodReference method) { return Modules.Scope(method.DeclaringType) + "|" + method.FullName; }
    void Record(string key, object value) { records[key] = json.Serialize(value); }
    void Type(TypeDefinition type) {
        Record("type:" + Modules.TypeName(type), new object[] { (int)type.Attributes, Modules.TypeName(type.BaseType), type.PackingSize, type.ClassSize });
    }
    void Field(FieldDefinition field) {
        Type(field.DeclaringType);
        Record("field:" + Modules.Scope(field.DeclaringType) + "|" + field.FullName,
            new object[] { (int)field.Attributes, Modules.TypeName(field.FieldType), field.HasConstant ? field.Constant : null,
                field.HasLayoutInfo ? field.Offset : -1 });
    }
    void Enqueue(MethodReference method) {
        if (!modules.assemblies.ContainsKey(Modules.Scope(method.DeclaringType))) return;
        var definition = method.Resolve();
        if (definition == null) throw new InvalidDataException("missing_dependency");
        if (seen.Add(MethodKey(definition))) {
            if (seen.Count > 256) throw new InvalidDataException("method_budget");
            pending.Enqueue(definition);
        }
    }
    object Operand(object value, Dictionary<Instruction, int> labels) {
        if (value == null) return null;
        var instruction = value as Instruction;
        if (instruction != null) return new object[] { "branch", labels[instruction] };
        var targets = value as Instruction[];
        if (targets != null) return new object[] { "switch", targets.Select(t => labels[t]).ToArray() };
        var method = value as MethodReference;
        if (method != null) { Enqueue(method); return new object[] { "method", MethodKey(method) }; }
        var field = value as FieldReference;
        if (field != null) {
            if (modules.assemblies.ContainsKey(Modules.Scope(field.DeclaringType))) {
                var definition = field.Resolve();
                if (definition == null) throw new InvalidDataException("missing_field_dependency");
                Field(definition);
            }
            return new object[] { "field", Modules.Scope(field.DeclaringType), field.FullName };
        }
        var type = value as TypeReference;
        if (type != null) return new object[] { "type", Modules.TypeName(type) };
        var variable = value as VariableDefinition;
        if (variable != null) return new object[] { "local", variable.Index, Modules.TypeName(variable.VariableType) };
        var parameter = value as ParameterDefinition;
        if (parameter != null) return new object[] { "parameter", parameter.Index, Modules.TypeName(parameter.ParameterType) };
        if (value is string || value is int || value is long || value is byte || value is sbyte || value is float || value is double) return value;
        throw new InvalidDataException("unsupported_operand");
    }
    static Dictionary<Instruction, int> Labels(IList<Instruction> instructions) {
        var result = new Dictionary<Instruction, int>();
        for (int i = 0; i < instructions.Count; i++) result.Add(instructions[i], i);
        return result;
    }
    void Method(MethodDefinition method) {
        Type(method.DeclaringType);
        if (!method.HasBody) {
            Record("method:" + MethodKey(method), new object[] { (int)method.Attributes, (int)method.ImplAttributes,
                method.IsPInvokeImpl ? method.PInvokeInfo.Module.Name : null,
                method.IsPInvokeImpl ? method.PInvokeInfo.EntryPoint : null,
                method.IsPInvokeImpl ? (int)method.PInvokeInfo.Attributes : 0 });
            return;
        }
        if (method.Body.Instructions.Count > 8192) throw new InvalidDataException("unsupported_method");
        var body = method.Body;
        instructions += body.Instructions.Count;
        if (instructions > 30000) throw new InvalidDataException("instruction_budget");
        var labels = Labels(body.Instructions);
        Func<Instruction, int> label = i => i == null ? body.Instructions.Count : labels[i];
        Record("method:" + MethodKey(method), new object[] {
            (int)method.Attributes, (int)method.ImplAttributes, body.InitLocals,
            body.Variables.Select(v => Modules.TypeName(v.VariableType)).ToArray(),
            body.Instructions.Select(i => new object[] { i.OpCode.Name, Operand(i.Operand, labels) }).ToArray(),
            body.ExceptionHandlers.Select(e => new object[] { (int)e.HandlerType, Modules.TypeName(e.CatchType), label(e.TryStart), label(e.TryEnd), label(e.HandlerStart), label(e.HandlerEnd), label(e.FilterStart) }).ToArray()
        });
    }
    static int Integer(Instruction instruction) {
        switch (instruction.OpCode.Code) {
            case Code.Ldc_I4_M1: return -1;
            case Code.Ldc_I4_0: return 0; case Code.Ldc_I4_1: return 1;
            case Code.Ldc_I4_2: return 2; case Code.Ldc_I4_3: return 3;
            case Code.Ldc_I4_4: return 4; case Code.Ldc_I4_5: return 5;
            case Code.Ldc_I4_6: return 6; case Code.Ldc_I4_7: return 7;
            case Code.Ldc_I4_8: return 8;
            case Code.Ldc_I4: case Code.Ldc_I4_S: return Convert.ToInt32(instruction.Operand);
            default: throw new InvalidDataException("unsupported_dispatch");
        }
    }
    void Route(MethodDefinition method, int channel) {
        // Check the dispatch prelude and only the selected channel's reachable
        // instructions. Other channels may gain unrelated chest/emote behavior.
        if (!method.HasBody || method.Body.ExceptionHandlers.Count != 0) throw new InvalidDataException("unsupported_dispatch");
        var all = method.Body.Instructions;
        var switches = all.Where(i => i.OpCode.Code == Code.Switch).ToArray();
        if (switches.Length != 1 || all.Count > 8192) throw new InvalidDataException("unsupported_dispatch");
        var dispatch = switches[0];
        int position = all.IndexOf(dispatch);
        if (position < 3 || all[position - 1].OpCode.Code != Code.Sub) throw new InvalidDataException("unsupported_dispatch");
        int index = channel - Integer(all[position - 2]);
        var targets = (Instruction[])dispatch.Operand;
        if (index < 0 || index >= targets.Length) throw new InvalidDataException("missing_channel");
        var selected = new HashSet<Instruction>(all.Take(position + 1));
        var todo = new Queue<Instruction>();
        todo.Enqueue(targets[index]);
        while (todo.Count > 0) {
            var current = todo.Dequeue();
            if (!selected.Add(current)) continue;
            if (current.OpCode.FlowControl == FlowControl.Return || current.OpCode.FlowControl == FlowControl.Throw) continue;
            var target = current.Operand as Instruction;
            if (target != null) todo.Enqueue(target);
            if (current.Operand is Instruction[]) throw new InvalidDataException("nested_dispatch");
            if (current.OpCode.FlowControl != FlowControl.Branch) {
                if (current.Next == null) throw new InvalidDataException("invalid_control_flow");
                todo.Enqueue(current.Next);
            }
        }
        var ordered = all.Where(selected.Contains).ToArray();
        var labels = Labels(ordered);
        Record("route:" + MethodKey(method), ordered.Select(i => new object[] { i.OpCode.Name,
            i == dispatch ? new object[] { "channel", channel, labels[targets[index]] } : Operand(i.Operand, labels) }).ToArray());
    }
    internal string Digest(FeatureSpec spec) {
        foreach (string key in spec.fields ?? new string[0]) Field(modules.FindField(key));
        foreach (string key in spec.packets ?? new string[0]) {
            var type = modules.FindType(key);
            Type(type);
            // Serialized packet shape includes the presence/absence of every field.
            Record("packet:" + key, type.Fields.Select(f => f.FullName).OrderBy(n => n, StringComparer.Ordinal).ToArray());
            foreach (var field in type.Fields) Field(field);
            foreach (var constructor in type.Methods.Where(m => m.IsConstructor)) Enqueue(constructor);
        }
        foreach (string key in spec.methods ?? new string[0]) foreach (var method in modules.FindMethods(key)) Enqueue(method);
        foreach (string key in spec.writers ?? new string[0]) {
            var field = modules.FindField(key);
            var matches = modules.types.Values.SelectMany(t => t.Methods).Where(m => m.HasBody &&
                m.Body.Instructions.Any(i => (i.OpCode.Code == Code.Stsfld || i.OpCode.Code == Code.Stfld) &&
                    i.Operand is FieldReference && ((FieldReference)i.Operand).FullName == field.FullName &&
                    Modules.Scope(((FieldReference)i.Operand).DeclaringType) == Modules.Scope(field.DeclaringType))).ToArray();
            if (matches.Length == 0) throw new InvalidDataException("missing_field_writer");
            foreach (var method in matches) Enqueue(method);
        }
        if (spec.route != null) Route(modules.FindMethod(spec.route), spec.channel);
        while (pending.Count > 0) Method(pending.Dequeue());
        if (records.Count == 0) throw new InvalidDataException("empty_feature");
        using (var buffer = new MemoryStream()) using (var writer = new BinaryWriter(buffer, Encoding.UTF8)) using (var hash = SHA256.Create()) {
            foreach (var record in records) { writer.Write(record.Key); writer.Write(record.Value); }
            writer.Flush();
            return BitConverter.ToString(hash.ComputeHash(buffer.ToArray())).Replace("-", "").ToLowerInvariant();
        }
    }
}

public static class FeatureProbe {
    public static int Main(string[] args) {
        try {
            if (args.Length != 2 || new FileInfo(args[1]).Length > 65536) throw new InvalidDataException();
            var json = new JavaScriptSerializer { MaxJsonLength = 65536 };
            var spec = json.Deserialize<ProbeSpec>(File.ReadAllText(args[1], Encoding.UTF8));
            if (spec.schema != 1 || spec.features == null || spec.features.Count < 1 || spec.features.Count > 16) throw new InvalidDataException();
            using (var modules = new Modules(args[0], spec.assemblies)) {
                var result = new SortedDictionary<string, string>(StringComparer.Ordinal);
                foreach (var row in spec.features) result.Add(row.Key, new Feature(modules).Digest(row.Value));
                Console.WriteLine(json.Serialize(result));
            }
            return 0;
        } catch {
            // Never emit game metadata, paths, or a stack trace to the parent/UI.
            Console.WriteLine("{\"error\":\"feature_probe_failed\"}");
            return 2;
        }
    }
}
