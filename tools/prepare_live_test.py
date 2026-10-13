"""Prepare a private, single-send review plan. Does not transmit any chat."""
import argparse
import json
from pathlib import Path
import time

from bongo_chat.environment import running_game,verify_build
from bongo_chat.steam import APP_ID,Steam
from bongo_chat.protocol import encode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--text',default='Bongo Cat Chat 앱 송수신 확인입니다')
    args=parser.parse_args()
    encode(args.text)
    if 'private' not in args.output.resolve().parts:
        parser.error('Use a private, Git-excluded output directory')
    game=running_game();verify_build(game.root);steam=Steam(game.root)
    try:
        steam.start();account=steam.account();app,lobby=steam.reported_game(account)
        if app!=APP_ID or lobby=='0' or account not in steam.members(lobby):
            raise RuntimeError('Destination cannot be independently confirmed')
        plan=dict(account=account,lobby=lobby,name=steam.room_name(lobby),pid=game.pid,created=game.created,
                  prepared=time.time(),text=args.text,count=1)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(target_name=plan['name'],members=len(steam.members(lobby)),text=plan['text'],count=1,sends=0),ensure_ascii=False))
    finally:steam.close()


if __name__=='__main__':main()
