// Entirely synthetic metadata/IL. No game code, assets, or identifiers.
using System;
using Mono.Cecil;
using Mono.Cecil.Cil;

public static class FeatureAssembly {
    static MethodDefinition Method(TypeDefinition type, string name, TypeReference result) {
        var method = new MethodDefinition(name, MethodAttributes.Public | MethodAttributes.Static, result);
        type.Methods.Add(method); return method;
    }
    public static void Main(string[] args) {
        string mode = args[1];
        using (var assembly = AssemblyDefinition.CreateAssembly(new AssemblyNameDefinition("Fixture", new Version(1, 0)), "Fixture", ModuleKind.Dll)) {
            var module = assembly.MainModule;
            var core = new TypeDefinition("Demo", "Core", TypeAttributes.Public | TypeAttributes.Class, module.TypeSystem.Object);
            module.Types.Add(core);
            if (mode == "metadata") {
                var noise = Method(core, "AddedUnrelatedMethod", module.TypeSystem.Int32);
                noise.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4, 990));
                noise.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            }
            var hidden = new FieldDefinition(mode == "missing" ? "RenamedHidden" : "Hidden", FieldAttributes.Public | FieldAttributes.Static,
                mode == "field_type" ? module.TypeSystem.Int32 : module.TypeSystem.Boolean);
            core.Fields.Add(hidden);
            var writer = Method(core, "SetHidden", module.TypeSystem.Void);
            writer.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4_0));
            writer.Body.Instructions.Add(Instruction.Create(OpCodes.Stsfld, hidden));
            writer.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            if (mode == "writer") {
                var added = Method(core, "NewHiddenWriter", module.TypeSystem.Void);
                added.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4_1));
                added.Body.Instructions.Add(Instruction.Create(OpCodes.Stsfld, hidden));
                added.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            }
            var helper = Method(core, "HiddenHelper", module.TypeSystem.Boolean);
            helper.Body.Instructions.Add(Instruction.Create(OpCodes.Ldsfld, hidden));
            if (mode == "privacy") {
                helper.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4_0));
                helper.Body.Instructions.Add(Instruction.Create(OpCodes.Ceq));
            }
            helper.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            var reader = Method(core, "GetHidden", module.TypeSystem.Boolean);
            reader.Body.Instructions.Add(Instruction.Create(OpCodes.Call, helper));
            reader.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            var sender = Method(core, "Send", module.TypeSystem.Int32);
            sender.Body.Instructions.Add(Instruction.Create(mode == "channel" ? OpCodes.Ldc_I4_4 : OpCodes.Ldc_I4_3));
            sender.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            var unrelated = Method(core, "Chest", module.TypeSystem.Int32);
            unrelated.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4, mode == "unrelated" ? 200 : 100));
            unrelated.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
            var packet = new TypeDefinition("Demo", "Packet", TypeAttributes.Public | TypeAttributes.Class, module.TypeSystem.Object);
            module.Types.Add(packet);
            packet.Fields.Add(new FieldDefinition("Channel", FieldAttributes.Public, module.TypeSystem.Int32));
            packet.Fields.Add(new FieldDefinition("Message", FieldAttributes.Public, module.TypeSystem.String));
            if (mode == "packet") packet.Fields.Add(new FieldDefinition("Encrypted", FieldAttributes.Public, module.TypeSystem.Boolean));
            var route = Method(core, "Route", module.TypeSystem.Int32);
            route.Parameters.Add(new ParameterDefinition(module.TypeSystem.Int32));
            var chest = Instruction.Create(OpCodes.Ldc_I4, mode == "other_channel" ? 201 : 101);
            var chat = Instruction.Create(OpCodes.Ldc_I4, mode == "route" ? 302 : 301);
            var emote = Instruction.Create(OpCodes.Ldc_I4, 401);
            var il = route.Body.Instructions;
            il.Add(Instruction.Create(OpCodes.Ldarg_0)); il.Add(Instruction.Create(OpCodes.Ldc_I4_2));
            il.Add(Instruction.Create(OpCodes.Sub));
            il.Add(Instruction.Create(OpCodes.Switch, new[] { chest, mode == "routing" ? emote : chat, emote }));
            il.Add(Instruction.Create(OpCodes.Ldc_I4_M1)); il.Add(Instruction.Create(OpCodes.Ret));
            il.Add(chest);
            if (mode == "other_channel") for (int i = 0; i < 10; i++) il.Add(Instruction.Create(OpCodes.Nop));
            il.Add(Instruction.Create(OpCodes.Ret)); il.Add(chat); il.Add(Instruction.Create(OpCodes.Ret));
            il.Add(emote); il.Add(Instruction.Create(OpCodes.Ret));
            assembly.Write(args[0]);
        }
    }
}
