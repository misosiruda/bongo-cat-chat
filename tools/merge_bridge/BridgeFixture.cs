// Synthetic bindings only. No game/Steam assemblies or processes are accessed.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using BongoCatChat.MergeBridge;

namespace UnityEngine.Events { public delegate void UnityAction(); }
namespace UnityEngine {
    public class Application { }
    class BeforeRenderHelper {
        internal struct OrderBlock { internal int order; internal Events.UnityAction callback; }
        static List<OrderBlock> s_OrderBlocks = new List<OrderBlock>();
    }
}
namespace Steamworks {
    public struct SteamInventoryResult_t { public int value; }
    public enum EResult { k_EResultOK = 1, Failed = 2 }
    public struct CSteamID { public ulong m_SteamID; }
    public static class SteamUser { public static CSteamID GetSteamID() { return new CSteamID { m_SteamID = 1 }; } }
}
namespace Heathen.SteamworksIntegration {
    public struct InventoryResult { public Steamworks.EResult result; }
    public class ItemData { public long quantity; public long GetTotalQuantity() { return quantity; } }
}
namespace Heathen.SteamworksIntegration.API {
    public class Inventory { public static class Client {
        static Dictionary<Steamworks.SteamInventoryResult_t, Action<Heathen.SteamworksIntegration.InventoryResult>> _mResultHandles = new Dictionary<Steamworks.SteamInventoryResult_t, Action<Heathen.SteamworksIntegration.InventoryResult>>();
        public static void Add(Action<Heathen.SteamworksIntegration.InventoryResult> callback) { _mResultHandles.Add(new Steamworks.SteamInventoryResult_t { value = 42 }, callback); }
        public static void Complete() { var cb = _mResultHandles.Values.Single(); cb(new Heathen.SteamworksIntegration.InventoryResult { result = Steamworks.EResult.k_EResultOK }); _mResultHandles.Clear(); }
    } }
}
namespace Steam.Exchanges {
    public class SteamTagExchange { public int InputAmount = 10; public string InputTagValue = "common"; }
    public class ExchangeSlot {
        public BongoCat.SteamItemRuntime ItemSlotted;
        public long SlottedAmount { get; private set; }
        public void SetItem(BongoCat.SteamItemRuntime item, long n) {
            if (ItemSlotted != null) ItemSlotted.CurrentlyInExchangeSlot -= SlottedAmount;
            ItemSlotted = item; SlottedAmount = n;
            if (item != null) item.CurrentlyInExchangeSlot += n;
        }
    }
}
namespace BongoCat {
    public class ItemBasic { public bool HasTagWithValue(string value) { return value == "common"; } }
    public class SteamItemRuntime {
        public bool IsCosmetic, IsEmote, IsUiTheme, Favorite, Event;
        public int Id, QualityCategoryWithInfo;
        public long CurrentlyInExchangeSlot;
        public ItemBasic Data = new ItemBasic();
        public Heathen.SteamworksIntegration.ItemData RuntimeData = new Heathen.SteamworksIntegration.ItemData();
    }
    public class CatInventory {
        public static CatInventory Instance = new CatInventory();
        public bool IsInitialized = true, FetchingItems;
        public List<SteamItemRuntime> Items = new List<SteamItemRuntime>();
    }
    public class ItemExchange {
        public static ItemExchange Instance = new ItemExchange();
        List<Steam.Exchanges.ExchangeSlot> _exchangeSlots = Enumerable.Range(0,10).Select(i => new Steam.Exchanges.ExchangeSlot()).ToList();
        bool _isExchanging;
        int _possibleExchanges;
        int _currentCategoryTabIndex = 1;
        List<Steam.Exchanges.SteamTagExchange> _exchanges = new List<Steam.Exchanges.SteamTagExchange> { new Steam.Exchanges.SteamTagExchange() };
        public bool IsVisible;
        public bool AllowFavoriteItems { get; set; }
        public bool ExcludeEventItems { get; set; }
        public int Selections, Merges;
        List<SteamItemRuntime> GetDuplicateItems(bool ignoreTab) { return CatInventory.Instance.Items.Where(i => i.RuntimeData.quantity > 1 && (!i.Favorite || AllowFavoriteItems) && (!i.Event || !ExcludeEventItems)).ToList(); }
        public bool IsItemExchangeable(SteamItemRuntime item) { return true; }
        void UpdateInteractable() { _possibleExchanges = (int)(_exchangeSlots.Where(s => s.ItemSlotted != null).Sum(s => s.SlottedAmount)/10); }
        public void SlotDuplicates() {
            Selections++;
            var item = GetDuplicateItems(false).First(i => _currentCategoryTabIndex < 3 ? i.IsCosmetic : i.IsEmote);
            foreach(var slot in _exchangeSlots) slot.SetItem(item,1);
            UpdateInteractable();
        }
        public class Closure {
            public SteamItemRuntime[] items;
            public void Complete(Heathen.SteamworksIntegration.InventoryResult result) {
                foreach (var item in items) item.RuntimeData.quantity--;
                foreach (var slot in Instance._exchangeSlots) slot.SetItem(null,1);
                Instance.UpdateInteractable(); Instance._isExchanging = false;
            }
        }
        public void TryExchange() {
            Merges++; _isExchanging = true;
            var closure = new Closure { items = _exchangeSlots.Select(s=>s.ItemSlotted).ToArray() };
            Heathen.SteamworksIntegration.API.Inventory.Client.Add(closure.Complete);
        }
    }
}
class Fixture {
    static string folder, epoch = new string('a',32), token = new string('b',64);
    static int checks;
    static long sequence;
    static bool interactive;
    static BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
    static object Call(string method, params object[] args) { return typeof(Bridge).GetMethod(method,flags).Invoke(null,args); }
    static JObject Json(string path) { using(var r = new JsonTextReader(new StringReader(File.ReadAllText(path)))) return JObject.Load(r,null); }
    static JObject Snap() { return (JObject)Call("Snapshot"); }
    static void Check(bool ok) { checks++; if (!ok) throw new Exception("check_"+checks); }
    static JObject Request(string op, string extra = "", string id = null, long age = 0, string expectedGroup = null, bool? expectedFavorites = null) {
        id = id ?? Guid.NewGuid().ToString("N");
        var observed=Snap();
        if (interactive) extra += ",\"sequence\":"+(++sequence)+",\"run_attempt\":\""+(string)observed["run_attempt"]+"\"";
        extra += ",\"expected_group\":\""+(expectedGroup ?? (string)observed["group"])+"\",\"favorites_allowed\":"+((expectedFavorites ?? (bool)observed["favorites_allowed"])?"true":"false")+",\"events_excluded\":"+((bool)observed["events_excluded"]?"true":"false");
        File.WriteAllText(Path.Combine(folder,"request.json"), "{\"id\":\""+id+"\",\"epoch\":\""+epoch+"\",\"token\":\""+token+"\",\"op\":\""+op+"\",\"issued_utc_ms\":"+(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()-age)+extra+"}");
        Call("Handle"); return Json(Path.Combine(folder,"response.json"));
    }
    static string Material() { var s=Snap(); return ",\"count\":1,\"selection\":\""+(string)s["selection"]+"\",\"selection_attempt\":\""+(string)s["selection_attempt"]+"\""; }
    public static void Main() {
        try { Run(); }
        catch (Exception e) {
            while(e != null) { Console.WriteLine(e.GetType().FullName); Console.WriteLine(e.Message); e=e.InnerException; }
            Environment.Exit(1);
        }
    }
    static void Run() {
        folder=Path.GetDirectoryName(typeof(Fixture).Assembly.Location);
        interactive=Environment.GetCommandLineArgs().Contains("--interactive");
        File.WriteAllText(Path.Combine(folder,"session.json"), "{\"protocol\":1,\"pid\":"+Process.GetCurrentProcess().Id+",\"process_start_ticks\":"+Process.GetCurrentProcess().StartTime.ToUniversalTime().Ticks+",\"epoch\":\""+epoch+"\",\"token\":\""+token+"\",\"test_budget\":2}");
        if (interactive) {
            string config=File.ReadAllText(Path.Combine(folder,"session.json"));
            File.WriteAllText(Path.Combine(folder,"session.json"),config.Replace("\"test_budget\":2","\"test_budget\":0,\"mode\":\"interactive\""));
        }
        var c=new BongoCat.SteamItemRuntime { Id=1,IsCosmetic=true };c.RuntimeData.quantity=41;
        var e=new BongoCat.SteamItemRuntime { Id=2,IsEmote=true };e.RuntimeData.quantity=21;
        BongoCat.CatInventory.Instance.Items.Add(c);BongoCat.CatInventory.Instance.Items.Add(e);
        Bridge.Install(); Bridge.Install();
        var x=BongoCat.ItemExchange.Instance;
        if (interactive) { RunInteractive(x); return; }
        Check((long)Snap()["available_exchanges"]==4);
        Check(!(bool)Request("select",age:5000)["ok"] && x.Selections==0);
        Check(!(bool)Request("select",expectedGroup:"emotes")["ok"] && x.Selections==0);
        x.AllowFavoriteItems=true;Check(!(bool)Request("select",expectedFavorites:false)["ok"] && x.Selections==0);x.AllowFavoriteItems=false;
        x.IsVisible=true;Check(!(bool)Request("select")["ok"]);x.IsVisible=false;
        Check((bool)Request("select")["ok"]);
        Check((long)Snap()["selected_units"]==10 && (int)Snap()["exchanges"]==1);
        Check((int)typeof(BongoCat.ItemExchange).GetField("_currentCategoryTabIndex",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(x)==1);
        Check(!(bool)Request("group",",\"group\":\"emotes\"")["ok"]);
        Check(!(bool)Request("merge",Material().Replace("\"count\":1","\"count\":2"))["ok"] && x.Merges==0);
        x.AllowFavoriteItems=true;Check(!(bool)Request("merge",Material())["ok"] && x.Merges==0);x.AllowFavoriteItems=false;
        Check((bool)Request("stop")["ok"] && (long)Snap()["selected_units"]==0);
        Check((bool)Request("group",",\"group\":\"emotes\"")["ok"] && (long)Snap()["available_exchanges"]==2);
        Check((bool)Request("select")["ok"]);
        string id=Guid.NewGuid().ToString("N"), material=Material();
        Check((bool)Request("merge",material,id)["ok"] && x.Merges==1);
        Check((bool)Request("merge",material,id)["ok"] && x.Merges==1);
        Check(!(bool)Request("select")["ok"] && x.Merges==1);
        Heathen.SteamworksIntegration.API.Inventory.Client.Complete();
        Check((int)((JObject)Snap()["receipt"])["completed"]==1 && e.RuntimeData.quantity==11 && c.RuntimeData.quantity==41);
        Check((bool)Request("group",",\"group\":\"cosmetics\"")["ok"]);
        Check((bool)Request("select")["ok"]);
        Check((bool)Request("merge",Material())["ok"] && x.Merges==2);
        Heathen.SteamworksIntegration.API.Inventory.Client.Complete();
        Check((int)Snap()["confirmed_completed"]==2 && c.RuntimeData.quantity==31);
        Check(!(bool)Request("select")["ok"] && x.Merges==2);
        Check((int)Json(Path.Combine(folder,"ledger.json"))["spent"]==2);
        Check((bool)Request("shutdown")["ok"]);
        Console.WriteLine("Bridge fixture: "+checks+" checks passed; synthetic exchanges="+x.Merges);
    }
    static void RunInteractive(BongoCat.ItemExchange x) {
        Check((int)Snap()["test_budget"]==0 && (string)Snap()["run_attempt"]=="");
        Check(!(bool)Request("select")["ok"] && x.Selections==0 && x.Merges==0);
        Check(!(bool)Request("begin",",\"limit\":0")["ok"]);
        Check((bool)Request("begin",",\"limit\":3")["ok"]);
        for (int i=0;i<3;i++) {
            Check((bool)Request("select")["ok"]);
            Check((bool)Request("merge",Material())["ok"] && x.Merges==i+1);
            Check(!(bool)Request("begin",",\"limit\":100")["ok"]);
            Heathen.SteamworksIntegration.API.Inventory.Client.Complete();
            Check((int)Snap()["spent"]==i+1 && (int)Snap()["confirmed_completed"]==i+1);
        }
        Check(!(bool)Request("select")["ok"] && x.Merges==3);
        Check((bool)Request("stop")["ok"] && (string)Snap()["run_attempt"]=="");
        Check((bool)Request("begin",",\"limit\":1")["ok"]);
        Check((bool)Request("select")["ok"]);
        Check((bool)Request("stop")["ok"] && (long)Snap()["selected_units"]==0 && (int)Snap()["test_budget"]==3);
        Check(!(bool)Request("select")["ok"] && x.Merges==3);
        for (int i=0;i<600;i++) Check((bool)Request("snapshot")["ok"]);
        Check((int)Json(Path.Combine(folder,"ledger.json"))["spent"]==3 && x.Merges==3);
        string previous=File.ReadAllText(Path.Combine(folder,"request.json"));
        Check((bool)Request("snapshot")["ok"]);
        File.WriteAllText(Path.Combine(folder,"request.json"),previous);
        Call("Handle");Check(!(bool)Json(Path.Combine(folder,"response.json"))["ok"] && x.Merges==3);
        Check((bool)Request("shutdown")["ok"]);
        Console.WriteLine("Interactive bridge fixture: "+checks+" checks passed; synthetic exchanges="+x.Merges);
    }
}
