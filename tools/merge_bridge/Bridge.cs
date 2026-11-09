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
using System.Threading;
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
        static bool installed, unknown, callbackSeen, callbackFailed, originalCallbackFailed;
        static volatile bool stopped;
        static bool interactive;
        static string runAttempt = "";
        static long commandSequence;
        static bool selectedFavorites, selectedEvents;
        static ulong account;
        static long nextPoll, nextSnapshot, lastCommand;
        static IList renderCallbacks;
        static object renderBlock;
        static UnityAction renderAction;
        static SynchronizationContext mainContext;
        static Timer mainPump;
        static int tickQueued;
        static string heartbeatRun = "";
        static long heartbeatSequence;
        static JObject lastReceipt;
        static FieldInfo slotsField, busyField, countField, categoryField, recipesField, handlesField;
        static MethodInfo duplicatesMethod;
        [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
        [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll")] static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool MoveFileEx(string from, string to, uint flags);
        [DllImport("kernel32.dll", EntryPoint = "ReplaceFileW", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool ReplaceFile(string target, string replacement, string backup, uint flags, IntPtr exclude, IntPtr reserved);
        static Stopwatch NewClock() { var clock = new Stopwatch(); clock.Start(); return clock; }
        static long StartTicks() { long c, e, k, u; if (!GetProcessTimes(GetCurrentProcess(), out c, out e, out k, out u)) throw new InvalidOperationException("process_unverified"); return c + 504911232000000000L; }

        static JObject ReadJson(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                var bytes = new byte[4097];
                int count = 0, read;
                while (count < bytes.Length && (read = stream.Read(bytes, count, bytes.Length - count)) > 0) count += read;
                if (count > 4096) throw new InvalidOperationException("oversized_request");
                using (var reader = new JsonTextReader(new StringReader(Encoding.UTF8.GetString(bytes, 0, count).TrimStart('\uFEFF'))))
                    return JObject.Load(reader, null);
            }
        }
        internal static JObject Object(params object[] pairs)
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
            // Repeatable observations/replies use ReplaceFile's compatible share
            // mode. Keep consumption ledgers on their existing publication path.
            bool published = (name == "snapshot.json" || name == "response.json") && File.Exists(target)
                ? ReplaceFile(target, tmp, null, 0, IntPtr.Zero, IntPtr.Zero) : MoveFileEx(tmp, target, 9);
            if (!published) throw new IOException("atomic_write_failed");
        }

        // Executed on an attached Mono worker. Only managed file/reflection/list APIs here.
        // BeforeRenderHelper.Invoke locks this same list and invokes callbacks on Unity's thread.
        static string ModuleIdentity(Assembly assembly)
        {
            var modules = assembly.GetModules();
            if (modules.Length != 1) throw new InvalidOperationException("automation_files_changed");
            return modules[0].ModuleVersionId.ToString("D");
        }
        internal static void VerifyAssemblyIdentity(JObject config)
        {
            // Compatibility is decided once by the metadata probe. Bind that
            // observation to the assemblies in this game, including an update
            // on disk while an older game process is still running.
            var identities = config["assembly_mvids"] as JObject;
            if (identities == null || identities.Count < 1 || identities.Count > 34)
                throw new InvalidOperationException("automation_files_changed");
            foreach (var required in new[] { typeof(ItemExchange).Assembly, typeof(Enumerable).Assembly })
                if ((string)identities[required.GetName().Name + ".dll"] != ModuleIdentity(required))
                    throw new InvalidOperationException("automation_files_changed");
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name = assembly.GetName().Name + ".dll";
                var expected = identities[name];
                if ((expected != null && (string)expected != ModuleIdentity(assembly)) ||
                    (name == "BongoAutoChest.dll" && expected == null))
                    throw new InvalidOperationException("automation_files_changed");
            }
        }
        public static void Install()
        {
            if (installed) return;
            string step = "bridge_init_0";
            try { InstallCore(ref step); }
            catch (Exception exception)
            {
                // Only this fixed code and allowlisted exception types enter a report.
                // Native diagnostics read fields without invoking exception.ToString().
                throw new InvalidOperationException(step, exception);
            }
        }
        static void InstallCore(ref string step)
        {
            step = "bridge_init_1";
            directory = Path.GetDirectoryName(typeof(Bridge).Assembly.Location);
            var config = ReadJson(Path.Combine(directory, "session.json"));
            step = "bridge_init_2";
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
            step = "bridge_init_3";
            try { VerifyAssemblyIdentity(config); }
            catch (InvalidOperationException)
            {
                File.WriteAllText(Path.Combine(directory, "compatibility-error.json"),
                    Object("epoch", epoch, "reason", "automation_files_changed").ToString(Formatting.None));
                throw;
            }
            step = "bridge_init_4";
            var ledgerPath = Path.Combine(directory, "ledger.json");
            if (File.Exists(ledgerPath))
            {
                var ledger = ReadJson(ledgerPath);
                if ((string)ledger["epoch"] != epoch) throw new InvalidOperationException("ledger_mismatch");
                spent = (int)ledger["spent"];
                if (spent < 0 || spent > maxRequests) throw new InvalidOperationException("ledger_invalid");
            }
            step = "bridge_init_5";
            var type = typeof(ItemExchange);
            slotsField = Field(type, "_exchangeSlots"); busyField = Field(type, "_isExchanging");
            countField = Field(type, "_possibleExchanges"); categoryField = Field(type, "_currentCategoryTabIndex");
            recipesField = Field(type, "_exchanges"); duplicatesMethod = type.GetMethod("GetDuplicateItems", Flags);
            if (duplicatesMethod == null) throw new InvalidOperationException("missing_duplicates");
            handlesField = Field(typeof(Heathen.SteamworksIntegration.API.Inventory.Client), "_mResultHandles");
            step = "bridge_init_6";
            var helper = typeof(UnityEngine.Application).Assembly.GetType("UnityEngine.BeforeRenderHelper");
            renderCallbacks = (IList)Field(helper, "s_OrderBlocks").GetValue(null);
            var blockType = helper.GetNestedType("OrderBlock", BindingFlags.NonPublic | BindingFlags.Public);
            renderBlock = Activator.CreateInstance(blockType);
            Field(blockType, "order").SetValue(renderBlock, int.MaxValue);
            renderAction = BootstrapMainLoop;
            Field(blockType, "callback").SetValue(renderBlock, renderAction);
            step = "bridge_init_7";
            lastCommand = Clock.ElapsedMilliseconds;
            lock (renderCallbacks) { renderCallbacks.Add(renderBlock); installed = true; }
        }

        static void BootstrapMainLoop()
        {
            if (stopped || mainPump != null) return;
            var context = SynchronizationContext.Current;
            if (context == null || context.GetType().FullName != "UnityEngine.UnitySynchronizationContext") return;
            mainThread = Thread.CurrentThread.ManagedThreadId;
            mainContext = context;
            // Rendering is used only once to acquire Unity's main-thread context.
            // Timer callbacks enqueue work; they never call a game or Unity API.
            mainPump = new Timer(QueueTick, null, 50, 50);
            lock (renderCallbacks) renderCallbacks.Remove(renderBlock);
        }
        static void QueueTick(object unused)
        {
            if (stopped || Interlocked.CompareExchange(ref tickQueued, 1, 0) != 0) return;
            try { mainContext.Post(RunQueuedTick, null); }
            catch { Interlocked.Exchange(ref tickQueued, 0); }
        }
        static void RunQueuedTick(object unused)
        {
            try { Tick(); }
            finally { Interlocked.Exchange(ref tickQueued, 0); }
        }

        sealed class GameNotReady : InvalidOperationException
        {
            internal GameNotReady(string reason) : base(reason) { }
        }
        static void RequireAccount()
        {
            ulong current = SteamUser.GetSteamID().m_SteamID;
            if (current == 0) throw new GameNotReady("game_unavailable");
            if (account != 0 && current != account) throw new InvalidOperationException("account_changed");
            if (account == 0) account = current;
        }
        static ItemExchange RequireGame()
        {
            RequireAccount();
            var x = ItemExchange.Instance;
            if (x == null || CatInventory.Instance == null) throw new GameNotReady("game_unavailable");
            if (!CatInventory.Instance.IsInitialized || CatInventory.Instance.FetchingItems)
                throw new GameNotReady("inventory_refreshing");
            return x;
        }
        static void RequireIdle(ItemExchange x)
        {
            if (ChestRuntime.BlocksMerge) throw new InvalidOperationException("chest_active");
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
            long? available = !ChestRuntime.BlocksMerge && !busy && pending == "" && units == 0 ? (long?)Available(x) : null;
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
            result["chest"] = ChestRuntime.Snapshot();
            return result;
        }
        static JObject UnavailableSnapshot(string reason)
        {
            // Transport liveness must not depend on a complete inventory read.
            // Unknown inventory fields cannot authorize selection or consumption.
            return Object("protocol", Protocol, "epoch", epoch, "pid", GetCurrentProcessId(),
                "captured_utc_ms", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "generation", ++generation,
                "main_thread", mainThread, "group", group, "ready", false, "reason", reason,
                "favorites_allowed", null, "events_excluded", null, "selected_units", 0, "exchanges", 0,
                "selection", "", "selection_attempt", selectionAttempt, "can_select", null,
                "exchanging", pending != "", "available_exchanges", null, "available_group", group,
                "pending_attempt", pending, "spent", spent, "test_budget", maxRequests,
                "mode", interactive ? "interactive" : "test", "run_attempt", runAttempt,
                "command_sequence", commandSequence, "per_request_limit", PerRequest,
                "confirmed_completed", completed, "receipt", null, "chest", ChestRuntime.Snapshot());
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
                if (age < -1000 || age > 3000) throw new GameNotReady("connection_recovering");
                if (interactive)
                {
                    long sequence = (long?)request["sequence"] ?? 0;
                    if (sequence <= commandSequence) throw new InvalidOperationException("request_replayed");
                    commandSequence = sequence;
                }
                string op = (string)request["op"];
                string operationId = (string)request["operation_id"] ?? id;
                if (!Guid.TryParseExact(operationId, "N", out parsed)) throw new InvalidOperationException("invalid_operation_id");
                // Stop and heartbeat do not need the inventory. A heartbeat can
                // renew only the exact run owned by this app, never a stopped run.
                if (op != "chest_stop") RequireAccount();
                if (op == "chest_stop") { ChestRuntime.Stop("user_stopped"); reply["ok"] = new JValue(true); }
                else if (op == "chest_heartbeat")
                {
                    if ((string)request["chest_run_attempt"] != ChestRuntime.RunAttempt)
                        throw new InvalidOperationException("run_not_authorized");
                    ChestRuntime.Heartbeat(); reply["ok"] = new JValue(true);
                }
                else
                {
                    var x = op == "snapshot" ? null : RequireGame(); lastCommand = Clock.ElapsedMilliseconds; error = "";
                    if (op == "select" || op == "merge" || op == "begin")
                    {
                        if ((string)request["expected_group"] != group) throw new InvalidOperationException("group_changed");
                        if ((bool?)request["favorites_allowed"] != FavoriteOption(x) || (bool?)request["events_excluded"] != EventOption(x))
                            throw new InvalidOperationException("settings_changed");
                        if (interactive && op != "begin" && (runAttempt == "" || (string)request["run_attempt"] != runAttempt))
                            throw new InvalidOperationException("run_not_authorized");
                    }
                    if (op == "snapshot") { }
                    else if (op == "chest_start")
                    {
                        RequireIdle(x);
                        if (!interactive || Units(x) != 0) throw new InvalidOperationException("run_not_authorized");
                        runAttempt = ""; maxRequests = spent;
                        ChestRuntime.Start(directory, request, operationId);
                    }
                    else if (op == "begin")
                    {
                        RequireIdle(x);
                        if (!interactive || Units(x) != 0) throw new InvalidOperationException("run_not_authorized");
                        int count = (int?)request["limit"] ?? 0;
                        if (count < 1 || count > int.MaxValue - spent) throw new InvalidOperationException("invalid_limit");
                        Atomic("authorization.json", Object("epoch", epoch, "run_attempt", operationId, "spent", spent, "authorized_total", spent + count));
                        runAttempt = operationId; maxRequests = spent + count; lastReceipt = null;
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
                    else if (op == "select") Select(x, operationId);
                    else if (op == "merge") Merge(x, request, operationId);
                    else if (op == "stop")
                    {
                        ClearOwned(x);
                        if (interactive) { runAttempt = ""; maxRequests = spent; }
                    }
                    else if (op == "shutdown")
                    {
                        if (pending != "" || Busy(x) || ChestRuntime.BlocksMerge) throw new InvalidOperationException("exchange_pending");
                        ClearOwned(x); stopped = true;
                    }
                    else throw new InvalidOperationException("unsupported_operation");
                    reply["ok"] = new JValue(true);
                }
            }
            catch (GameNotReady e)
            {
                // Positive acknowledgement that nothing was dispatched. The app
                // may retry with a NEW transport id and the same operation id.
                reply["reason"] = new JValue(e.Message); reply["deferred"] = new JValue(true);
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
            // Independent mailbox: no acknowledgement wait and no command queue
            // contention can delay the owning app's heartbeat.
            try { ReadHeartbeat(); } catch { }
            // A sharing conflict is a transport failure, not a game-state failure.
            try { Handle(); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            catch { error = "bridge_observation_failed"; }
            string unavailable = "";
            try
            {
                RequireGame();
                // Inventory refresh/read failures are observations, not a permanent
                // connection fault. Clear only this transient error after the game
                // validates again; retain command errors and unknown results.
                if (error == "bridge_observation_failed") error = "";
                ChestRuntime.Tick();
                if ((!interactive || runAttempt == "") && pending == "" && owned != "" && now - lastCommand > 15000) ClearOwned(RequireGame());
            }
            catch (GameNotReady e) { unavailable = e.Message; ChestRuntime.Tick(false); }
            catch (InvalidOperationException e)
            {
                if (e.Message == "account_changed") { error = "target_changed"; ChestRuntime.Stop("game_unavailable"); }
                else { unavailable = "bridge_observation_failed"; ChestRuntime.Tick(false); }
            }
            catch { unavailable = "bridge_observation_failed"; ChestRuntime.Tick(false); }
            if (now >= nextSnapshot || stopped)
            {
                nextSnapshot = now + 250;
                // A transient reader sharing conflict must not poison a later
                // valid observation. The client's source timestamp still expires.
                JObject snapshot;
                try { snapshot = unavailable == "" ? Snapshot() : UnavailableSnapshot(unavailable); }
                catch { snapshot = UnavailableSnapshot(error == "target_changed" ? error : "bridge_observation_failed"); }
                try { Atomic("snapshot.json", snapshot); } catch { }
            }
            if (stopped)
            {
                if (mainPump != null) mainPump.Dispose();
                // Removing the last callback while Invoke owns this list is safe under its monitor.
                lock (renderCallbacks) renderCallbacks.Remove(renderBlock);
            }
        }
        static void ReadHeartbeat()
        {
            string path = Path.Combine(directory, "heartbeat.json");
            if (!File.Exists(path)) return;
            var value = ReadJson(path);
            string run = (string)value["chest_run_attempt"];
            if ((string)value["epoch"] != epoch || (string)value["token"] != token ||
                string.IsNullOrEmpty(run) || run != ChestRuntime.RunAttempt) return;
            double age = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - (double)value["issued_utc_ms"];
            long sequence = (long)value["sequence"];
            if (age < 0 || age > 1500 || sequence < 1 || run == heartbeatRun && sequence <= heartbeatSequence) return;
            RequireAccount();
            heartbeatRun = run; heartbeatSequence = sequence;
            ChestRuntime.Heartbeat(age / 1000);
        }
    }
}

// Adapted from misosiruda/bongo-cat-auto-chest (MIT, copyright 2026 misosiruda).
// Own-code orchestration only: original OpenChest/Callback and OnClicked perform game actions.
namespace BongoCatChat.MergeBridge
{
    internal static class ChestRuntime
    {
        const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
        const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public;
        static readonly Stopwatch Clock = Stopwatch.StartNew();
        internal static Func<double> Now = delegate { return Clock.Elapsed.TotalSeconds; };
        internal static Func<bool> Hotkey = delegate { return Down(0x11) && Down(0x12) && Down(0x78); };
        static readonly Random Random = new Random();
        static readonly Dictionary<string, Gate> Gates = new Dictionary<string, Gate>();
        static FieldInfo itemField, openingField, waitingField, exchangerField, exchangingField;
        static FieldInfo targetField, typeField, activeField, clickedField, memberField, keyField, objectField;
        static Type legacy;
        static bool initialized, supported, armed, enabled, own = true, others, unknown, pending, hotkeyDown, takenOver;
        static double minDelay = 3, maxDelay = 8, nextAction, nextObserve, lease, requestedAt;
        static int attempted, confirmed, failed, remoteRequested;
        static string reason = "disconnected", directory, attempt = "";
        static BongoCat.Multiplayer.OpenChestForMember[] buttons = new BongoCat.Multiplayer.OpenChestForMember[0];
        static double nextScan;
        [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
        static bool Down(int key) { return (GetAsyncKeyState(key) & 0x8000) != 0; }
        sealed class Gate
        {
            internal bool Ready, Attempted;
            internal double ReadyAt;
            internal void Observe(bool ready, double now)
            {
                if (ready && !Ready) ReadyAt = now + Delay();
                Ready = ready;
                if (!ready) Attempted = false;
            }
            internal bool CanAttempt(double now) { return Ready && !Attempted && now >= ReadyAt; }
        }
        sealed class Candidate
        {
            internal Gate Gate;
            internal Shop Shop;
            internal ShopItem Item;
            internal BongoCat.Multiplayer.OpenChestForMember Button;
        }
        static FieldInfo Field(Type type, string name)
        {
            var f = type.GetField(name, Private);
            if (f == null) throw new InvalidOperationException("unsupported_chest");
            return f;
        }
        static void Initialize()
        {
            if (initialized) return;
            initialized = true;
            try
            {
                // The common installer validates chest/merge/inventory features.
                // Do not maintain a second, narrower whole-assembly allowlist.
                itemField = Field(typeof(Shop), "_shopItem"); openingField = Field(typeof(Shop), "_openingChest");
                waitingField = Field(typeof(ShopItem), "_waitingForServer"); exchangerField = Field(typeof(ShopItem), "_chestExchanger");
                exchangingField = typeof(Steam.ChestExchanger).GetField("IsExchanging", Static);
                targetField = Field(typeof(BongoCat.Multiplayer.OpenChestForMember), "_targetUser");
                typeField = Field(typeof(BongoCat.Multiplayer.OpenChestForMember), "_chestType");
                activeField = Field(typeof(BongoCat.Multiplayer.OpenChestForMember), "_setChestActive");
                clickedField = Field(typeof(BongoCat.Multiplayer.OpenChestForMember), "_hasClicked");
                memberField = Field(typeof(BongoCat.Multiplayer.SetActiveBasedOnLobbyMemberValue), "_lobbyMemberData");
                keyField = Field(typeof(BongoCat.Multiplayer.SetActiveBasedOnLobbyMemberValue), "_key");
                objectField = Field(typeof(BongoCat.Multiplayer.SetActiveBasedOnLobbyMemberValue), "_gameObject");
                if (exchangingField == null) throw new InvalidOperationException("unsupported_chest");
                legacy = FindLegacy();
                supported = true; reason = "ready";
            }
            catch { reason = "unsupported_chest"; }
        }
        static Type FindLegacy()
        {
            return AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType("BongoAutoChest.AutoChest")).FirstOrDefault(t => t != null);
        }
        static bool Busy(Shop shop)
        {
            if (shop == null) return false;
            var item = (ShopItem)itemField.GetValue(shop);
            return (bool)openingField.GetValue(shop) || item != null && (bool)waitingField.GetValue(item);
        }
        static bool AnyBusy()
        {
            return Busy(Shop.NormalShop) || Busy(Shop.EmoteShop) || (bool)exchangingField.GetValue(null);
        }
        static void RequireLegacyStopped(bool replace)
        {
            if (legacy == null) legacy = FindLegacy();
            if (legacy == null) return;
            var fault = legacy.GetField("Faulted", Static);
            var enable = legacy.GetField("Enabled", Static);
            var requests = legacy.GetField("OwnRequests", Static);
            if (fault == null || enable == null || requests == null || fault.FieldType != typeof(bool) || enable.FieldType != typeof(bool))
                throw new InvalidOperationException("legacy_unverified");
            var outstanding = requests.GetValue(null) as IDictionary;
            if (outstanding == null || outstanding.Count != 0) throw new InvalidOperationException("legacy_busy");
            if (takenOver)
            {
                if (!(bool)fault.GetValue(null) || (bool)enable.GetValue(null)) throw new InvalidOperationException("legacy_unverified");
                return;
            }
            if (!replace) throw new InvalidOperationException("legacy_confirmation_required");
            // On Unity's thread and idle: stop the legacy Tick before it can dispatch another action.
            // Its INI, binary and original backups remain unchanged. It stays stopped for this game lifetime.
            fault.SetValue(null, true); enable.SetValue(null, false); takenOver = true;
        }
        internal static bool BlocksMerge { get { return armed || pending || unknown; } }
        internal static string RunAttempt { get; private set; }
        internal static JObject Snapshot()
        {
            Initialize();
            return Bridge.Object("supported", supported, "armed", armed, "enabled", enabled,
                "pending", pending, "unknown", unknown, "reason", reason,
                "run_attempt", RunAttempt ?? "",
                "legacy_detected", legacy != null, "legacy_taken_over", takenOver,
                "attempted", attempted, "own_confirmed", confirmed,
                "failed", failed, "remote_requested", remoteRequested,
                "own", own, "others", others, "min_delay", minDelay, "max_delay", maxDelay);
        }
        static double Delay() { return minDelay + (Random.Next(1000000) / 1000000.0) * (maxDelay - minDelay); }
        internal static void Start(string folder, JObject request, string id)
        {
            Initialize();
            if (!supported || unknown || pending || armed) throw new InvalidOperationException("chest_unavailable");
            var config = request["chest_settings"] as JObject;
            if (config == null || config.Count != 4 || config["own"] == null || config["others"] == null ||
                config["own"].Type != JTokenType.Boolean || config["others"].Type != JTokenType.Boolean ||
                config["min_delay"] == null || config["max_delay"] == null ||
                !(config["min_delay"].Type == JTokenType.Integer || config["min_delay"].Type == JTokenType.Float) ||
                !(config["max_delay"].Type == JTokenType.Integer || config["max_delay"].Type == JTokenType.Float))
                throw new InvalidOperationException("invalid_chest_settings");
            double lo = (double)config["min_delay"], hi = (double)config["max_delay"];
            bool nextOwn = (bool)config["own"], nextOthers = (bool)config["others"];
            if (double.IsNaN(lo) || double.IsNaN(hi) || lo < 1 || hi > 300 || hi < lo || !(nextOwn || nextOthers))
                throw new InvalidOperationException("invalid_chest_settings");
            if (AnyBusy()) throw new InvalidOperationException("chest_busy");
            RequireLegacyStopped((bool?)request["replace_legacy"] == true);
            directory = folder;
            own = nextOwn; others = nextOthers; minDelay = lo; maxDelay = hi;
            // Durable evidence is written before arming, and before every consuming request.
            WriteLedger("armed", id);
            RunAttempt = id;
            lease = Now() + 3; nextAction = Now() + Delay();
            hotkeyDown = Hotkey();
            armed = enabled = true; reason = "running";
        }
        internal static void Heartbeat(double sourceAge = 0)
        {
            if (!armed) return;
            double now = Now();
            // Lease expiry suspends dispatch. Only this still-authorized run's
            // owning app can renew it; Stop and unknown results remain terminal.
            lease = now + 3 - sourceAge;
        }
        internal static void Stop(string why) { armed = enabled = false; if (!unknown) reason = why; }
        static void WriteLedger(string state, string id)
        {
            var value = Bridge.Object("state", state, "attempt", id, "attempted", attempted,
                "own_confirmed", confirmed, "failed", failed, "remote_requested", remoteRequested);
            string target = Path.Combine(directory, "chest-ledger.json");
            File.WriteAllText(target + ".tmp", value.ToString(Formatting.None));
            if (!MoveFileEx(target + ".tmp", target, 9)) throw new IOException("chest_ledger_failed");
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool MoveFileEx(string from, string to, uint flags);
        static Gate Observe(string key, bool ready, double now)
        {
            Gate gate;
            if (!Gates.TryGetValue(key, out gate))
            {
                if (Gates.Count >= 512) throw new InvalidOperationException("chest_capacity");
                gate = new Gate(); Gates.Add(key, gate);
            }
            gate.Observe(ready, now); return gate;
        }
        static void Own(Shop shop, string key, List<Candidate> candidates, double now)
        {
            if (shop == null) return;
            var gate = Observe(key, shop.ChestIsReady, now);
            var item = (ShopItem)itemField.GetValue(shop);
            if (own && gate.CanAttempt(now) && item != null && item.gameObject.activeSelf && !Busy(shop) && item.CanBuy())
                candidates.Add(new Candidate { Gate = gate, Shop = shop, Item = item });
        }
        static void Remote(BongoCat.Multiplayer.OpenChestForMember button, List<Candidate> candidates, double now)
        {
            if (button == null || !button.gameObject.scene.IsValid()) return;
            var target = (SteamUserData)targetField.GetValue(button);
            if (target == null || target.Data.Equals(UserData.Me)) return;
            BongoCat.Multiplayer.LobbyMemberInstance instance;
            if (!BongoCat.Multiplayer.MultiplayerLobbyReferences.GameplayInstances.TryGetValue(target.Data, out instance) || instance == null) return;
            var active = (BongoCat.Multiplayer.SetActiveBasedOnLobbyMemberValue)activeField.GetValue(button);
            if (active == null) return;
            var member = (SteamLobbyMemberData)memberField.GetValue(active);
            if (member == null || !member.Data.lobby.Equals(LobbyData.Current)) return;
            string metadataKey = (string)keyField.GetValue(active);
            bool ready;
            if (!bool.TryParse(member.Data[metadataKey], out ready)) return;
            var gate = Observe("remote:" + member.Data.lobby.ToString() + ":" + target.Data.IdStr + ":" + metadataKey, ready, now);
            // This rearms the game's UI lock only after a real not-ready observation.
            if (!ready) { button.Reset(); return; }
            if ((bool)clickedField.GetValue(button)) gate.Attempted = true;
            var visual = (UnityEngine.GameObject)objectField.GetValue(active);
            if (!others || !gate.CanAttempt(now) || instance.IsHidden || !button.isActiveAndEnabled || visual == null || !visual.activeInHierarchy) return;
            Shop shop = (ChestType)typeField.GetValue(button) == ChestType.Emote ? Shop.EmoteShop : Shop.NormalShop;
            if (shop == null) return;
            var item = (ShopItem)itemField.GetValue(shop);
            if (item != null && item.CanBuy()) candidates.Add(new Candidate { Gate = gate, Shop = shop, Item = item, Button = button });
        }
        internal static void Tick(bool gameReady = true)
        {
            if (!armed && !pending) return;
            double now = Now();
            try
            {
                if (pending && now - requestedAt > 30) { unknown = true; Stop("result_unverified"); reason = "result_unverified"; }
                if (!armed) return;
                if (now >= lease) { reason = "connection_recovering"; return; }
                if (!gameReady) { reason = "inventory_refreshing"; return; }
                RequireLegacyStopped(false);
                bool pressed = Hotkey();
                if (pressed && !hotkeyDown) { enabled = !enabled; nextAction = now + Delay(); }
                hotkeyDown = pressed;
                if (!enabled) { reason = "paused"; return; }
                reason = pending ? "waiting_result" : "running";
                if (now < nextObserve || pending || unknown) return;
                nextObserve = now + .5;
                var candidates = new List<Candidate>();
                Own(Shop.NormalShop, "own:normal", candidates, now); Own(Shop.EmoteShop, "own:emote", candidates, now);
                if (others && LobbyData.Current.IsValid)
                {
                    if (now >= nextScan) { buttons = UnityEngine.Resources.FindObjectsOfTypeAll<BongoCat.Multiplayer.OpenChestForMember>(); nextScan = now + 3; }
                    foreach (var button in buttons) Remote(button, candidates, now);
                }
                if (now < nextAction || AnyBusy() || candidates.Count == 0) return;
                var priority = candidates.Where(c => c.Button == null).ToList();
                var pool = priority.Count > 0 ? priority : candidates;
                var selected = pool[Random.Next(pool.Count)];
                selected.Gate.Attempted = true; nextAction = now + Delay();
                attempt = Guid.NewGuid().ToString("N"); attempted++;
                WriteLedger("requested", attempt);
                if (selected.Button != null)
                {
                    selected.Button.OnClicked();
                    if ((bool)clickedField.GetValue(selected.Button)) remoteRequested++;
                    else failed++;
                    WriteLedger("remote_requested", attempt);
                    return; // Submission never claims recipient delivery.
                }
                // Keep the original exchanger's token/retry behavior and exact original game result processing.
                // Only initiation is adapted to receive a correlated callback without patching ShopItem.Callback.
                var item = selected.Item;
                var exchanger = (Steam.ChestExchanger)exchangerField.GetValue(item);
                if (exchanger == null) throw new InvalidOperationException("chest_unavailable");
                pending = true; requestedAt = now;
                waitingField.SetValue(item, true); selected.Shop.SetLoadingVisuals();
                bool seen = false;
                exchanger.OpenChest(delegate(int itemId)
                {
                    if (seen) return;
                    seen = true;
                    try
                    {
                        item.Callback(itemId, true);
                        if (itemId == -1) failed++; else confirmed++;
                        pending = false; nextAction = Now() + Delay();
                        WriteLedger(itemId == -1 ? "failed" : "confirmed", attempt);
                    }
                    catch { unknown = true; Stop("result_unverified"); reason = "result_unverified"; }
                });
            }
            catch { unknown = true; Stop("chest_fault"); reason = "chest_fault"; }
        }
    }
}
