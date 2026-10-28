"""Bounded, opt-in native read probe. Never sends, joins or changes the game.

Only counts/statuses are reported; message bodies and identifiers are discarded.
Run with --seconds 30. No chat database is opened.
"""
import argparse
import json
import time

from bongo_chat.environment import running_game, verify_build
from bongo_chat.memory import GameMemory
from bongo_chat.steam import Steam
from bongo_chat.worker import LiveConnection


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=15)
    args=parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error("seconds must be 1..600")
    game=running_game();build=verify_build(game.root)
    memory=GameMemory(game);steam=None
    started=time.monotonic()
    try:
        memory.discover()
        discovery=round(time.monotonic()-started,2)
        steam=Steam(game.root);steam.start()
        connection=LiveConnection(game,memory,steam,read_only=True)
        states=set();received=0;reactions=0;profiles=0;member_count=0
        end=time.monotonic()+args.seconds
        while time.monotonic()<end:
            state,members,changed=connection.snapshot()
            states.add(state["state"]);profiles=max(profiles,len(state["profiles"]));member_count=len(state["members"])
            context={key:state[key] for key in ("account","lobby","generation")}
            events=steam.pump(context,members,accept=not changed and state["lobby_verified"])
            received+=sum(event['type']=='message' for event in events)
            reactions+=sum(event['type']=='reaction' for event in events)
            time.sleep(.15)
        print(json.dumps(dict(build=build, discovery_seconds=discovery, observe_seconds=args.seconds,
            states=sorted(states), profile_count=profiles, member_count=member_count,
            chat_callbacks_decoded=received, reaction_callbacks_decoded=reactions, rejected_packets=steam.rejected,
            sends=0, lobby_mutations=0, process_writes=0, plaintext_saved=False)))
    finally:
        if steam:steam.close()
        memory.close()
    print(json.dumps(dict(game_process_survived_app_shutdown=game.alive(),peer_screen_verified=False)))


if __name__=="__main__":main()
