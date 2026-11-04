// State-machine acceptance with synthetic game/Steam types and deterministic time.
using System;
using System.Collections;
using System.IO;
using System.Reflection;
using BongoCat;
using BongoCat.Multiplayer;
using BongoCatChat.MergeBridge;
using Heathen.SteamworksIntegration;
using Newtonsoft.Json.Linq;
static class ChestFixture {
    static int checks;
    static double now;
    static bool key;
    const BindingFlags F = BindingFlags.Static | BindingFlags.NonPublic;
    static void Set(string name, object value) { typeof(ChestRuntime).GetField(name,F).SetValue(null,value); }
    static void Check(bool condition, string message) { checks++; if (!condition) throw new Exception("Chest: " + message); }
    static JObject Config(bool own = true, bool others = false, bool replace = false) {
        return Bridge.Object("chest_settings", Bridge.Object("own",own,"others",others,"min_delay",1,"max_delay",1),"replace_legacy",replace);
    }
    static void Step(double seconds = 1) { now += seconds; ChestRuntime.Heartbeat(); ChestRuntime.Tick(); }
    static void Reject(Action action, string message) { bool refused = false; try { action(); } catch { refused = true; } Check(refused,message); }
    internal static void Run(string folder) {
        Shop.NormalShop = new Shop(); Shop.EmoteShop = new Shop();
        Check(!(bool)ChestRuntime.Snapshot()["supported"],"unknown binary is blocked");
        // Bind only the synthetic types, without weakening the shipped binary allowlist.
        foreach (var pair in new[] { new[] {"itemField","_shopItem"},new[] {"openingField","_openingChest"} })
            Set(pair[0],typeof(Shop).GetField(pair[1],BindingFlags.Instance|BindingFlags.NonPublic));
        foreach (var pair in new[] { new[] {"waitingField","_waitingForServer"},new[] {"exchangerField","_chestExchanger"} })
            Set(pair[0],typeof(ShopItem).GetField(pair[1],BindingFlags.Instance|BindingFlags.NonPublic));
        Set("exchangingField",typeof(Steam.ChestExchanger).GetField("IsExchanging",F));
        foreach (var pair in new[] { new[] {"targetField","_targetUser"},new[] {"typeField","_chestType"},new[] {"activeField","_setChestActive"},new[] {"clickedField","_hasClicked"} })
            Set(pair[0],typeof(OpenChestForMember).GetField(pair[1],BindingFlags.Instance|BindingFlags.NonPublic));
        foreach (var pair in new[] { new[] {"memberField","_lobbyMemberData"},new[] {"keyField","_key"},new[] {"objectField","_gameObject"} })
            Set(pair[0],typeof(SetActiveBasedOnLobbyMemberValue).GetField(pair[1],BindingFlags.Instance|BindingFlags.NonPublic));
        Set("supported",true); Set("initialized",true);
        ChestRuntime.Now = delegate { return now; }; ChestRuntime.Hotkey = delegate { return key; };
        Check(!ChestRuntime.BlocksMerge && !(bool)ChestRuntime.Snapshot()["armed"],"connection never arms");
        ChestRuntime.Start(folder,Config(),"first");
        var item = Shop.NormalShop.Item;
        Shop.NormalShop.ChestIsReady = true;
        Step(); Check(item.Exchanger.Requests == 0,"discovery waits");
        Step(); Check(item.Exchanger.Requests == 1 && (bool)ChestRuntime.Snapshot()["pending"],"one own request");
        Step(2); Check(item.Exchanger.Requests == 1 && item.Results == 0,"no retry while pending");
        item.Exchanger.Complete(123); item.Exchanger.Callback(123);
        Check(item.Results == 1 && item.Charges == 1 && (int)ChestRuntime.Snapshot()["own_confirmed"] == 1,"correlated callback exactly once");
        Step(); Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check(item.Exchanger.Requests == 2,"new observed ready cycle");
        ChestRuntime.Stop("user_stopped"); Step();
        Check(item.Exchanger.Requests == 2 && ChestRuntime.BlocksMerge,"stop preserves pending result");
        item.Exchanger.Complete(-1);
        Check(!ChestRuntime.BlocksMerge && (int)ChestRuntime.Snapshot()["failed"] == 1,"failure is not success");
        ChestRuntime.Start(folder,Config(),"hotkey");
        key = true; Step(); Check(!(bool)ChestRuntime.Snapshot()["enabled"],"hotkey pauses");
        Step(); Check(!(bool)ChestRuntime.Snapshot()["enabled"],"held hotkey does not repeat");
        key = false; Step(); key = true; Step(); Check((bool)ChestRuntime.Snapshot()["enabled"],"hotkey resumes armed run");
        now += 4; ChestRuntime.Tick(); Check(!(bool)ChestRuntime.Snapshot()["armed"],"lost app lease disarms");
        key = false; Step(); key = true; Step(); Check(!(bool)ChestRuntime.Snapshot()["armed"],"hotkey cannot rearm");
        key = false;
        ChestRuntime.Start(folder,Config(),"late-heartbeat");
        now += 3; ChestRuntime.Heartbeat(); ChestRuntime.Tick();
        Check(!(bool)ChestRuntime.Snapshot()["armed"] && (string)ChestRuntime.Snapshot()["reason"] == "app_disconnected","late heartbeat cannot revive expired lease");
        Check(item.Exchanger.Requests == 2,"expired heartbeat dispatches no chest");
        var malformed = Config(); ((JObject)malformed["chest_settings"])["min_delay"] = new JValue("1");
        Reject(delegate { ChestRuntime.Start(folder,malformed,"invalid-number"); },"numeric strings rejected before arming");
        ChestRuntime.Hotkey = delegate { throw new InvalidOperationException("synthetic hotkey failure"); };
        Reject(delegate { ChestRuntime.Start(folder,Config(),"failed-start"); },"hotkey initialization failure is refused");
        Check(!ChestRuntime.BlocksMerge,"failed start never arms consumption");
        ChestRuntime.Hotkey = delegate { return key; };
        var remote = new OpenChestForMember("synthetic-peer");
        UnityEngine.Resources.Buttons = new[] {remote};
        MultiplayerLobbyReferences.GameplayInstances[remote.User] = new LobbyMemberInstance();
        remote.Active.Member.Ready = true;
        ChestRuntime.Start(folder,Config(false,true),"remote");
        MultiplayerLobbyReferences.GameplayInstances[remote.User].IsHidden = true;
        Step(); Step(); Check(remote.Requests == 0,"hidden player excluded");
        MultiplayerLobbyReferences.GameplayInstances[remote.User].IsHidden = false;
        Step(); Check(remote.Requests == 1 && (int)ChestRuntime.Snapshot()["remote_requested"] == 1,"visible remote request counted separately");
        Step(); Step(); Check(remote.Requests == 1,"remote one request per ready cycle");
        remote.Active.Member.Ready = false; Step(); remote.Active.Member.Ready = true; Step(); Step();
        Check(remote.Requests == 2,"remote reset requires real false observation");
        ChestRuntime.Stop("user_stopped");
        // An existing legacy dispatcher is stopped only by explicit takeover, while idle.
        Set("legacy",typeof(Legacy));
        Reject(delegate { ChestRuntime.Start(folder,Config(),"no-consent"); },"legacy requires explicit takeover");
        Legacy.OwnRequests.Add(1,"pending");
        Reject(delegate { ChestRuntime.Start(folder,Config(replace:true),"legacy-pending"); },"legacy pending blocks takeover");
        Legacy.OwnRequests.Clear();
        ChestRuntime.Start(folder,Config(replace:true),"takeover");
        Check(Legacy.Faulted && !Legacy.Enabled,"legacy disabled before new dispatch");
        Legacy.Enabled = true; Step();
        Check(!(bool)ChestRuntime.Snapshot()["armed"] && (bool)ChestRuntime.Snapshot()["unknown"],"legacy reactivation stops dispatcher");
        Set("unknown",false); Legacy.Enabled = false;
        ChestRuntime.Start(folder,Config(),"timeout");
        Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check((bool)ChestRuntime.Snapshot()["pending"],"timeout case dispatched");
        Step(31);
        Check((bool)ChestRuntime.Snapshot()["unknown"] && !(bool)ChestRuntime.Snapshot()["armed"],"timeout is unresolved and disarmed");
        Reject(delegate { ChestRuntime.Start(folder,Config(),"retry"); },"unknown result cannot restart");
        Console.WriteLine("Chest fixture: " + checks + " checks passed; synthetic requests only.");
    }
    static class Legacy {
        internal static bool Faulted, Enabled = true;
        internal static IDictionary OwnRequests = new System.Collections.Generic.Dictionary<int,string>();
    }
}
