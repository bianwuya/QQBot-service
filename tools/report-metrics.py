"""Read-only local metrics report; no network and no Store crash-recovery side effects."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from metrics import offline


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--days',type=int,choices=[1,7,30],default=1)
    p.add_argument('--db',default=str(Path(__file__).resolve().parents[1]/'state/bot.sqlite3'))
    p.add_argument('--json',action='store_true')
    args=p.parse_args()
    try:report=offline(args.db,args.days)
    except Exception:
        print('无法只读打开指标数据库；请核对本机路径和权限。',file=sys.stderr);return 1
    if args.json:print(json.dumps(report,ensure_ascii=False,indent=2))
    else:
        print('统计范围：'+report['from']+' ～ '+report['through'])
        for name,dimensions in report['metrics'].items():
            for dimension,row in dimensions.items():
                print('{} {} count={} total={} avg={}'.format(name,dimension,row['samples'],row['total'],row['average']))
    return 0


if __name__=='__main__':raise SystemExit(main())
