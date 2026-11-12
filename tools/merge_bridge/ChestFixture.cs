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
        Check((bool)ChestRuntime.Snapshot()["supported"],"shared compatibility-approved fixture binds chest without another hash gate");
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
        now += 4; ChestRuntime.Tick(); Check((bool)ChestRuntime.Snapshot()["armed"] && (string)ChestRuntime.Snapshot()["reason"] == "connection_recovering","lost lease suspends the authorized run");
        Check(item.Exchanger.Requests == 2,"expired lease dispatches nothing");
        ChestRuntime.Heartbeat(); ChestRuntime.Tick();
        Check((string)ChestRuntime.Snapshot()["reason"] == "running","same owner heartbeat restores run");
        ChestRuntime.Stop("user_stopped");
        key = false; Step(); key = true; Step(); Check(!(bool)ChestRuntime.Snapshot()["armed"],"hotkey and heartbeat cannot rearm a user stop");
        key = false;
        ChestRuntime.Start(folder,Config(),"late-heartbeat");
        now += 3; ChestRuntime.Tick();
        Check((bool)ChestRuntime.Snapshot()["armed"] && (string)ChestRuntime.Snapshot()["reason"] == "connection_recovering","expired lease waits for the owning app");
        Check(item.Exchanger.Requests == 2,"expired lease dispatches no chest");
        Check(!(bool)Fixture.Request("chest_heartbeat",",\"chest_run_attempt\":\"other-run\"",refreshing:true)["ok"],"another run cannot renew the lease");
        ChestRuntime.Tick();
        Check((string)ChestRuntime.Snapshot()["reason"] == "connection_recovering","wrong heartbeat leaves run suspended");
        Fixture.Pulse("other-run",1);
        Fixture.Pulse("late-heartbeat",1,age:5000);
        ChestRuntime.Tick();
        Check((string)ChestRuntime.Snapshot()["reason"] == "connection_recovering","wrong and stale heartbeat files cannot renew");
        Fixture.Pulse("late-heartbeat",1,refreshing:true);
        double renewed=(double)typeof(ChestRuntime).GetField("lease",F).GetValue(null);
        now += .25;
        Fixture.Pulse("late-heartbeat",1);
        Check((double)typeof(ChestRuntime).GetField("lease",F).GetValue(null)==renewed,"rereading heartbeat sequence does not extend lease");
        Fixture.Pulse("late-heartbeat",2,age:1000);
        double remaining=(double)typeof(ChestRuntime).GetField("lease",F).GetValue(null)-now;
        Check(remaining>1.9 && remaining<=2,"transport age is deducted from lease");
        Check((bool)Fixture.Request("chest_heartbeat",",\"chest_run_attempt\":\"late-heartbeat\"",refreshing:true)["ok"],"own heartbeat works during inventory refresh");
        ChestRuntime.Tick(false);
        Check((bool)ChestRuntime.Snapshot()["armed"] && (string)ChestRuntime.Snapshot()["reason"] == "inventory_refreshing","inventory refresh keeps authorization without dispatch");
        Check(item.Exchanger.Requests == 2,"inventory wait dispatches no chest");
        Check((bool)Fixture.Request("chest_stop",refreshing:true)["ok"],"user stop works during inventory refresh");
        Check(!(bool)ChestRuntime.Snapshot()["armed"],"stop revokes the recovering run");
        Fixture.Pulse("late-heartbeat",3);
        Check(!(bool)ChestRuntime.Snapshot()["armed"],"heartbeat file never restarts a stopped run");
        Fixture.Request("snapshot");
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
        ChestRuntime.Start(folder,Config(),"delayed-result");
        Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check((bool)ChestRuntime.Snapshot()["pending"],"delayed request dispatched");
        int requests = item.Exchanger.Requests, failures = (int)ChestRuntime.Snapshot()["failed"];
        var lateFailure = item.Exchanger.Callback;
        Step(31); Step(90);
        var waiting = ChestRuntime.Snapshot();
        Check((bool)waiting["armed"] && (bool)waiting["pending"] && !(bool)waiting["unknown"]
            && (string)waiting["reason"] == "result_delayed","slow result keeps the same run waiting");
        Check(ChestRuntime.BlocksMerge && item.Exchanger.Requests == requests,"no other request while waiting");
        Reject(delegate { ChestRuntime.Start(folder,Config(),"retry"); },"cannot start a second run while waiting");
        item.Exchanger.Complete(-1);
        Check((int)ChestRuntime.Snapshot()["failed"] == failures + 1 && !(bool)ChestRuntime.Snapshot()["pending"],
            "late failure is recorded and resolves the pending request");
        Step(); Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check(item.Exchanger.Requests == requests + 1 && ChestRuntime.RunAttempt == "delayed-result",
            "next ready chest opens without a new start after late failure");
        lateFailure(-1);
        Check((bool)ChestRuntime.Snapshot()["pending"] && (int)ChestRuntime.Snapshot()["failed"] == failures + 1,
            "duplicate old callback cannot resolve a new request");
        Step(31);
        int successes = (int)ChestRuntime.Snapshot()["own_confirmed"];
        item.Exchanger.Complete(123);
        Step(); Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check((int)ChestRuntime.Snapshot()["own_confirmed"] == successes + 1 && item.Exchanger.Requests == requests + 2,
            "next ready chest opens without a new start after late success");
        Step(31);
        ChestRuntime.Stop("user_stopped"); Step(90);
        Check((string)ChestRuntime.Snapshot()["reason"] == "user_stopped" && ChestRuntime.BlocksMerge,
            "user stop while waiting preserves the pending receipt");
        item.Exchanger.Complete(123);
        Step(); Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Check(!ChestRuntime.BlocksMerge && item.Exchanger.Requests == requests + 2,
            "late receipt after user stop never rearms the run");

        ChestRuntime.Start(folder,Config(),"receipt-write-failure");
        Shop.NormalShop.ChestIsReady = false; Step(); Shop.NormalShop.ChestIsReady = true; Step(); Step();
        Step(31);
        using (File.Open(Path.Combine(folder,"chest-ledger.json"),FileMode.Open,FileAccess.Read,FileShare.Read))
            item.Exchanger.Complete(123);
        Step();
        var fault = ChestRuntime.Snapshot();
        Check((bool)fault["unknown"] && !(bool)fault["armed"] && (string)fault["reason"] == "result_unverified",
            "a late callback whose receipt cannot be saved still stops the run");
        Reject(delegate { ChestRuntime.Start(folder,Config(),"retry"); },"receipt write failure cannot start a new run");
        Console.WriteLine("Chest fixture: " + checks + " checks passed; synthetic requests only.");
    }
    static class Legacy {
        internal static bool Faulted, Enabled = true;
        internal static IDictionary OwnRequests = new System.Collections.Generic.Dictionary<int,string>();
    }
}
