// Fixed-purpose, opt-in bridge. The game DLL is referenced, never redistributed.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Runtime.InteropServices;
using BongoCat;
using Heathen.SteamworksIntegration;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Steam.Exchanges;
using Steamworks;
using UnityEngine.Events;

namespace BongoCatChat.MergeBridge
{
    public static class Bridge
    {
        const int Protocol = 1;
        const int PerRequest = 1;
        static readonly BindingFlags Flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
        static readonly Stopwatch Clock = NewClock();
        static readonly Dictionary<string, JObject> Replies = new Dictionary<string, JObject>();
        static string lastRequest = "";
        static string directory, epoch, token, group = "cosmetics", owned = "", selectionAttempt = "", pending = "", error = "";
        static int maxRequests, spent, completed, mainThread, generation;
        static bool installed, stopped, unknown, callbackSeen, callbackFailed, originalCallbackFailed;
        static bool interactive;
        static string runAttempt = "";
        static long commandSequence;
        static bool selectedFavorites, selectedEvents;
        static ulong account;
        static long nextPoll, nextSnapshot, lastCommand;
        static IList renderCallbacks;
        static object renderBlock;
        static UnityAction renderAction;
        static JObject lastReceipt;
        static FieldInfo slotsField, busyField, countField, categoryField, recipesField, handlesField;
        static MethodInfo duplicatesMethod;
        [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
        [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll")] static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool MoveFileEx(string from, string to, uint flags);
        static Stopwatch NewClock() { var clock = new Stopwatch(); clock.Start(); return clock; }
        static long StartTicks() { long c, e, k, u; if (!GetProcessTimes(GetCurrentProcess(), out c, out e, out k, out u)) throw new InvalidOperationException("process_unverified"); return c + 504911232000000000L; }

        static JObject ReadJson(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                if (stream.Length > 4096) throw new InvalidOperationException("oversized_request");
            using (var reader = new JsonTextReader(new StringReader(File.ReadAllText(path))))
                return JObject.Load(reader, null);
        }
        static JObject Object(params object[] pairs)
        {
            var result = new JObject();
            for (int i = 0; i < pairs.Length; i += 2)
                result[(string)pairs[i]] = pairs[i + 1] as JToken ?? new JValue(pairs[i + 1]);
            return result;
        }

        static FieldInfo Field(Type type, string name) { var f = type.GetField(name, Flags); if (f == null) throw new InvalidOperationException("missing_field:" + name); return f; }
        static bool Busy(ItemExchange x) { return (bool)busyField.GetValue(x); }
        static List<ExchangeSlot> Slots(ItemExchange x) { return (List<ExchangeSlot>)slotsField.GetValue(x); }
        static bool FavoriteOption(ItemExchange x) { return (bool)typeof(ItemExchange).GetProperty("AllowFavoriteItems", Flags).GetValue(x, null); }
        static bool EventOption(ItemExchange x) { return (bool)typeof(ItemExchange).GetProperty("ExcludeEventItems", Flags).GetValue(x, null); }
        static bool Matches(SteamItemRuntime item) { return group == "cosmetics" ? item.IsCosmetic : item.IsEmote || item.IsUiTheme; }
        static long Units(ItemExchange x) { return Slots(x).Where(s => s.ItemSlotted != null).Sum(s => s.SlottedAmount); }
        static string Fingerprint(ItemExchange x)
        {
            var selected = Slots(x).Where(s => s.ItemSlotted != null).ToArray();
            if (selected.Length == 0) return "";
            var value = string.Join(";", selected.Select(s => s.ItemSlotted.Id.ToString() + ":" + s.SlottedAmount.ToString() + ":" + s.ItemSlotted.RuntimeData.GetTotalQuantity().ToString()).ToArray());
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(epoch + value))).Replace("-", "");
        }
        static void Atomic(string name, JObject value)
        {
            string target = Path.Combine(directory, name), tmp = target + ".tmp";
            File.WriteAllText(tmp, value.ToString(Formatting.None));
            if (!MoveFileEx(tmp, target, 9)) throw new IOException("atomic_write_failed");
        }

        // Executed on an attached Mono worker. Only managed file/reflection/list APIs here.
        // BeforeRenderHelper.Invoke locks this same list and invokes callbacks on Unity's thread.
        public static void Install()
        {
            if (installed) return;
            directory = Path.GetDirectoryName(typeof(Bridge).Assembly.Location);
            var config = ReadJson(Path.Combine(directory, "session.json"));
            if ((int)config["protocol"] != Protocol || (int)config["pid"] != GetCurrentProcessId() ||
                (long)config["process_start_ticks"] != StartTicks())
                throw new InvalidOperationException("process_mismatch");
            epoch = (string)config["epoch"]; token = (string)config["token"];
            maxRequests = (int)config["test_budget"];
            interactive = (string)config["mode"] == "interactive";
            if (epoch.Length != 32 || token.Length != 64 || maxRequests < 0 || maxRequests > 2)
                throw new InvalidOperationException("invalid_session");
            // Connecting never arms consumption. The UI must explicitly begin a run.
            if (interactive && maxRequests != 0) throw new InvalidOperationException("invalid_session");
            var ledgerPath = Path.Combine(directory, "ledger.json");
            if (File.Exists(ledgerPath))
            {
                var ledger = ReadJson(ledgerPath);
                if ((string)ledger["epoch"] != epoch) throw new InvalidOperationException("ledger_mismatch");
                spent = (int)ledger["spent"];
                if (spent < 0 || spent > maxRequests) throw new InvalidOperationException("ledger_invalid");
            }
            var type = typeof(ItemExchange);
            slotsField = Field(type, "_exchangeSlots"); busyField = Field(type, "_isExchanging");
            countField = Field(type, "_possibleExchanges"); categoryField = Field(type, "_currentCategoryTabIndex");
            recipesField = Field(type, "_exchanges"); duplicatesMethod = type.GetMethod("GetDuplicateItems", Flags);
            if (duplicatesMethod == null) throw new InvalidOperationException("missing_duplicates");
            handlesField = Field(typeof(Heathen.SteamworksIntegration.API.Inventory.Client), "_mResultHandles");
            var helper = typeof(UnityEngine.Application).Assembly.GetType("UnityEngine.BeforeRenderHelper");
            renderCallbacks = (IList)Field(helper, "s_OrderBlocks").GetValue(null);
            var blockType = helper.GetNestedType("OrderBlock", BindingFlags.NonPublic | BindingFlags.Public);
            renderBlock = Activator.CreateInstance(blockType);
            Field(blockType, "order").SetValue(renderBlock, int.MaxValue);
            renderAction = Tick;
            Field(blockType, "callback").SetValue(renderBlock, renderAction);
            installed = true;
            lastCommand = Clock.ElapsedMilliseconds;
            lock (renderCallbacks) renderCallbacks.Add(renderBlock);
        }

        static ItemExchange RequireGame()
        {
            var x = ItemExchange.Instance;
            if (x == null || CatInventory.Instance == null || !CatInventory.Instance.IsInitialized || CatInventory.Instance.FetchingItems)
                throw new InvalidOperationException("game_unavailable");
            ulong current = SteamUser.GetSteamID().m_SteamID;
            if (current == 0 || account != 0 && current != account) throw new InvalidOperationException("account_changed");
            if (account == 0) account = current;
            return x;
        }
        static void RequireIdle(ItemExchange x)
        {
            if (unknown || pending != "" || Busy(x)) throw new InvalidOperationException("unresolved_exchange");
            if (x.IsVisible) throw new InvalidOperationException("manual_exchange_screen_open");
        }
        static List<SteamItemRuntime> Eligible(ItemExchange x)
        {
            var recipes = (List<SteamTagExchange>)recipesField.GetValue(x);
            return ((List<SteamItemRuntime>)duplicatesMethod.Invoke(x, new object[] { true }))
                .Where(i => Matches(i) && x.IsItemExchangeable(i) && recipes.Any(r => r.InputAmount == 10 && i.Data.HasTagWithValue(r.InputTagValue))).ToList();
        }
        static long Available(ItemExchange x)
        {
            return Eligible(x).GroupBy(i => i.QualityCategoryWithInfo)
                .Sum(g => g.Sum(i => Math.Max(0L, i.RuntimeData.GetTotalQuantity() - 1)) / 10);
        }
        static void ClearOwned(ItemExchange x)
        {
            if (owned == "" || Busy(x) || x.IsVisible || Fingerprint(x) != owned) return;
            foreach (var slot in Slots(x)) if (slot.ItemSlotted != null) slot.SetItem(null, 1);
            typeof(ItemExchange).GetMethod("UpdateInteractable", Flags).Invoke(x, null);
            owned = "";
        }
        static JObject Snapshot()
        {
            var x = RequireGame();
            bool busy = Busy(x);
            if (pending != "" && callbackSeen && !busy && !originalCallbackFailed)
            {
                lastReceipt = Object("attempt", pending, "completed", callbackFailed ? 0 : 1,
                    "finished", true, "failed", callbackFailed);
                if (!callbackFailed) completed++;
                pending = ""; owned = "";
            }
            long units = Units(x);
            bool ready = !stopped && !unknown && !x.IsVisible && error == "";
            long? available = !busy && pending == "" && units == 0 ? (long?)Available(x) : null;
            var result = Object("protocol", Protocol, "epoch", epoch, "pid", GetCurrentProcessId(),
                "captured_utc_ms", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "generation", ++generation,
                "main_thread", mainThread, "group", group, "ready", ready,
                "reason", stopped ? "closed" : unknown ? "result_unverified" : x.IsVisible ? "manual_exchange_screen_open" : error == "" ? "ready" : error,
                "merge_visible", x.IsVisible, "exchanging", busy, "favorites_allowed", FavoriteOption(x),
                "events_excluded", EventOption(x), "selected_units", units, "exchanges", (int)countField.GetValue(x),
                "selection", units == 0 ? "" : Fingerprint(x), "selection_attempt", selectionAttempt,
                "available_exchanges", available == null ? JValue.CreateNull() : new JValue(available.Value),
                "available_group", group, "can_select", available == null ? JValue.CreateNull() : new JValue(available > 0),
                "pending_attempt", pending, "spent", spent, "test_budget", maxRequests,
                "mode", interactive ? "interactive" : "test", "run_attempt", runAttempt, "command_sequence", commandSequence,
                "per_request_limit", PerRequest, "confirmed_completed", completed,
                "receipt", lastReceipt == null ? (JToken)JValue.CreateNull() : lastReceipt);
            return result;
        }
        static void Select(ItemExchange x, string id)
        {
            RequireIdle(x);
            if (Units(x) != 0 || (int)countField.GetValue(x) != 0) throw new InvalidOperationException("existing_selection");
            if (spent >= maxRequests) throw new InvalidOperationException("test_budget_exhausted");
            selectedFavorites = FavoriteOption(x); selectedEvents = EventOption(x);
            int oldCategory = (int)categoryField.GetValue(x);
            try
            {
                categoryField.SetValue(x, group == "cosmetics" ? 0 : 3);
                x.SlotDuplicates();
            }
            finally { categoryField.SetValue(x, oldCategory); owned = Fingerprint(x); }
            selectionAttempt = id; lastReceipt = null;
            if (Units(x) != 10 || (int)countField.GetValue(x) != 1)
            {
                ClearOwned(x);
                throw new InvalidOperationException("selection_not_one_exchange");
            }
        }
        static void Merge(ItemExchange x, JObject request, string id)
        {
            RequireIdle(x);
            if ((int?)request["count"] != PerRequest || spent >= maxRequests) throw new InvalidOperationException("test_budget_exhausted");
            if (owned == "" || (string)request["selection"] != owned || Fingerprint(x) != owned ||
                (string)request["selection_attempt"] != selectionAttempt || Units(x) != 10 || (int)countField.GetValue(x) != 1)
                throw new InvalidOperationException("selection_changed");
            if (selectedFavorites != FavoriteOption(x) || selectedEvents != EventOption(x)) throw new InvalidOperationException("settings_changed");
            var allowed = new HashSet<SteamItemRuntime>(Eligible(x));
            if (Slots(x).Any(s => s.ItemSlotted != null && (!allowed.Contains(s.ItemSlotted) ||
                s.ItemSlotted.RuntimeData.GetTotalQuantity() - s.ItemSlotted.CurrentlyInExchangeSlot < 1)))
                throw new InvalidOperationException("protection_changed");
            var handles = (Dictionary<SteamInventoryResult_t, Action<InventoryResult>>)handlesField.GetValue(null);
            var before = new HashSet<SteamInventoryResult_t>(handles.Keys);
            // Reserve BEFORE invoking. A crash/timeout never makes this attempt reusable.
            Atomic("ledger.json", Object("epoch", epoch, "spent", spent + 1, "run_attempt", runAttempt, "authorized_total", maxRequests));
            spent++; pending = id; callbackSeen = callbackFailed = originalCallbackFailed = false;
            try
            {
                x.TryExchange();
                var added = handles.Keys.Where(k => !before.Contains(k)).ToArray();
                if (added.Length != 1) throw new InvalidOperationException("result_handle_unverified");
                var key = added[0]; var original = handles[key];
                if (original == null || original.Target == null || original.Method.DeclaringType.FullName != "BongoCat.ItemExchange+<>c__DisplayClass54_0" ||
                    original.Method.Name != "<ExchangeRoutine>b__2") throw new InvalidOperationException("result_callback_unverified");
                var closureItems = (SteamItemRuntime[])Field(original.Target.GetType(), "items").GetValue(original.Target);
                if (!closureItems.SequenceEqual(Slots(x).Where(s => s.ItemSlotted != null).Select(s => s.ItemSlotted)))
                    throw new InvalidOperationException("result_materials_unverified");
                handles[key] = delegate(InventoryResult value)
                {
                    try { original(value); }
                    catch { originalCallbackFailed = true; unknown = true; error = "game_callback_failed"; }
                    finally { callbackFailed = value.result != EResult.k_EResultOK; callbackSeen = true; }
                };
            }
            catch { unknown = true; error = "result_unverified"; throw; }
        }
        static void Handle()
        {
            string path = Path.Combine(directory, "request.json");
            if (!File.Exists(path)) return;
            JObject request = ReadJson(path);
            string id = (string)request["id"];
            Guid parsed;
            if (!Guid.TryParseExact(id, "N", out parsed) || (string)request["token"] != token || (string)request["epoch"] != epoch) return;
            if (id == lastRequest) return;
            JObject reply;
            if (Replies.TryGetValue(id, out reply)) { Atomic("response.json", reply); lastRequest = id; return; }
            reply = Object("id", id, "epoch", epoch, "ok", false);
            try
            {
                if (!interactive && Replies.Count >= 512) throw new InvalidOperationException("session_capacity");
                double age = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - (double)request["issued_utc_ms"];
                if (age < -1000 || age > 3000) throw new InvalidOperationException("request_expired");
                if (interactive)
                {
                    long sequence = (long?)request["sequence"] ?? 0;
                    if (sequence <= commandSequence) throw new InvalidOperationException("request_replayed");
                    commandSequence = sequence;
                }
                string op = (string)request["op"];
                var x = RequireGame(); lastCommand = Clock.ElapsedMilliseconds; error = "";
                if (op == "select" || op == "merge" || op == "begin")
                {
                    if ((string)request["expected_group"] != group) throw new InvalidOperationException("group_changed");
                    if ((bool?)request["favorites_allowed"] != FavoriteOption(x) || (bool?)request["events_excluded"] != EventOption(x))
                        throw new InvalidOperationException("settings_changed");
                    if (interactive && op != "begin" && (runAttempt == "" || (string)request["run_attempt"] != runAttempt))
                        throw new InvalidOperationException("run_not_authorized");
                }
                if (op == "snapshot") { }
                else if (op == "begin")
                {
                    RequireIdle(x);
                    if (!interactive || Units(x) != 0) throw new InvalidOperationException("run_not_authorized");
                    int count = (int?)request["limit"] ?? 0;
                    if (count < 1 || count > int.MaxValue - spent) throw new InvalidOperationException("invalid_limit");
                    Atomic("authorization.json", Object("epoch", epoch, "run_attempt", id, "spent", spent, "authorized_total", spent + count));
                    runAttempt = id; maxRequests = spent + count; lastReceipt = null;
                }
                else if (op == "group")
                {
                    RequireIdle(x);
                    if (Units(x) != 0) throw new InvalidOperationException("existing_selection");
                    string next = (string)request["group"];
                    if (next != "cosmetics" && next != "emotes") throw new InvalidOperationException("invalid_group");
                    group = next; selectionAttempt = ""; lastReceipt = null;
                    if (interactive) { runAttempt = ""; maxRequests = spent; }
                }
                else if (op == "select") Select(x, id);
                else if (op == "merge") Merge(x, request, id);
                else if (op == "stop")
                {
                    ClearOwned(x);
                    if (interactive) { runAttempt = ""; maxRequests = spent; }
                }
                else if (op == "shutdown")
                {
                    if (pending != "" || Busy(x)) throw new InvalidOperationException("exchange_pending");
                    ClearOwned(x); stopped = true;
                }
                else throw new InvalidOperationException("unsupported_operation");
                reply["ok"] = new JValue(true);
            }
            catch (Exception e) { error = e is InvalidOperationException ? e.Message : "game_exception"; reply["reason"] = new JValue(error); }
            // Interactive sessions use a monotonic sequence to reject old commands,
            // even after the bounded response cache fills. No mutation is retried.
            if (Replies.Count < 512) Replies[id] = reply;
            Atomic("response.json", reply);
            lastRequest = id;
        }
        static void Tick()
        {
            if (stopped) return;
            if (mainThread == 0)
            {
                if (System.Threading.SynchronizationContext.Current == null || System.Threading.SynchronizationContext.Current.GetType().Name != "UnitySynchronizationContext") return;
                mainThread = System.Threading.Thread.CurrentThread.ManagedThreadId;
            }
            if (System.Threading.Thread.CurrentThread.ManagedThreadId != mainThread) return;
            long now = Clock.ElapsedMilliseconds;
            if (now < nextPoll) return;
            nextPoll = now + 50;
            try
            {
                Handle();
                if (pending == "" && owned != "" && now - lastCommand > 15000) ClearOwned(RequireGame());
            }
            catch { error = "bridge_observation_failed"; }
            if (now >= nextSnapshot || stopped)
            {
                nextSnapshot = now + 250;
                // A transient reader sharing conflict must not poison a later
                // valid observation. The client's source timestamp still expires.
                try { Atomic("snapshot.json", Snapshot()); } catch { }
            }
            if (stopped)
            {
                // Removing the last callback while Invoke owns this list is safe under its monitor.
                lock (renderCallbacks) renderCallbacks.Remove(renderBlock);
            }
        }
    }
}
