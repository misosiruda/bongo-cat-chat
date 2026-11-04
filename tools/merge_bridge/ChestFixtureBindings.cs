// Synthetic chest bindings. Never references or starts the installed game.
using System;
using System.Collections.Generic;
namespace UnityEngine {
    public struct Scene { public bool IsValid() { return true; } }
    public class GameObject { public bool activeSelf = true, activeInHierarchy = true; public Scene scene; }
    public static class Resources {
        public static BongoCat.Multiplayer.OpenChestForMember[] Buttons = new BongoCat.Multiplayer.OpenChestForMember[0];
        public static T[] FindObjectsOfTypeAll<T>() { return (T[])(object)Buttons; }
    }
}
namespace Heathen.SteamworksIntegration {
    public struct UserData {
        public static UserData Me = new UserData { IdStr = "self" };
        public string IdStr;
        public override bool Equals(object other) { return other is UserData && ((UserData)other).IdStr == IdStr; }
        public override int GetHashCode() { return IdStr.GetHashCode(); }
    }
    public class SteamUserData { public UserData Data; }
    public struct LobbyData {
        public static LobbyData Current = new LobbyData { Id = 1 };
        public int Id;
        public bool IsValid { get { return Id != 0; } }
        public override string ToString() { return Id.ToString(); }
    }
    public class MemberData {
        public LobbyData lobby = LobbyData.Current;
        public bool Ready;
        public string this[string key] { get { return Ready.ToString(); } }
    }
    public class SteamLobbyMemberData { public MemberData Data = new MemberData(); }
}
namespace Steam {
    public class ChestExchanger {
        static bool IsExchanging;
        public Action<int> Callback;
        public int Requests;
        public void OpenChest(Action<int> callback) { Requests++; Callback = callback; IsExchanging = true; }
        public void Complete(int result) { IsExchanging = false; Callback(result); }
    }
}
namespace BongoCat {
    public enum ChestType { Normal, Emote }
    public class Shop {
        public static Shop NormalShop, EmoteShop;
        public bool ChestIsReady;
        ShopItem _shopItem;
        bool _openingChest;
        public Shop() { _shopItem = new ShopItem(this); }
        public ShopItem Item { get { return _shopItem; } }
        public void SetLoadingVisuals() { }
    }
    public class ShopItem {
        bool _waitingForServer;
        Steam.ChestExchanger _chestExchanger = new Steam.ChestExchanger();
        Shop shop;
        public bool Affordable = true;
        public int Results, Charges;
        public UnityEngine.GameObject gameObject = new UnityEngine.GameObject();
        public ShopItem(Shop value) { shop = value; }
        public bool CanBuy() { return Affordable; }
        public Steam.ChestExchanger Exchanger { get { return _chestExchanger; } }
        public void Callback(int result, bool charge) {
            _waitingForServer = false; shop.ChestIsReady = false; Results++;
            if (result != -1 && charge) Charges++;
        }
    }
}
namespace BongoCat.Multiplayer {
    public class LobbyMemberInstance { public bool IsHidden; }
    public static class MultiplayerLobbyReferences {
        public static Dictionary<Heathen.SteamworksIntegration.UserData,LobbyMemberInstance> GameplayInstances = new Dictionary<Heathen.SteamworksIntegration.UserData,LobbyMemberInstance>();
    }
    public class SetActiveBasedOnLobbyMemberValue {
        Heathen.SteamworksIntegration.SteamLobbyMemberData _lobbyMemberData = new Heathen.SteamworksIntegration.SteamLobbyMemberData();
        string _key = "ready";
        UnityEngine.GameObject _gameObject = new UnityEngine.GameObject();
        public Heathen.SteamworksIntegration.MemberData Member { get { return _lobbyMemberData.Data; } }
        public UnityEngine.GameObject Visual { get { return _gameObject; } }
    }
    public class OpenChestForMember {
        Heathen.SteamworksIntegration.SteamUserData _targetUser;
        BongoCat.ChestType _chestType;
        SetActiveBasedOnLobbyMemberValue _setChestActive = new SetActiveBasedOnLobbyMemberValue();
        bool _hasClicked;
        public bool isActiveAndEnabled = true;
        public UnityEngine.GameObject gameObject = new UnityEngine.GameObject();
        public int Requests;
        public OpenChestForMember(string name) { _targetUser = new Heathen.SteamworksIntegration.SteamUserData { Data = new Heathen.SteamworksIntegration.UserData { IdStr = name } }; }
        public Heathen.SteamworksIntegration.UserData User { get { return _targetUser.Data; } }
        public SetActiveBasedOnLobbyMemberValue Active { get { return _setChestActive; } }
        public void Reset() { _hasClicked = false; }
        public void OnClicked() { if (!_hasClicked) { _hasClicked = true; Requests++; } }
    }
}
