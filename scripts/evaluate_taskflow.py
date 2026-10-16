#!/usr/bin/env python3
"""Compare exported run JSON against independently human-confirmed labels."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taskflow.evaluation import evaluate

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--labels',type=Path,required=True);parser.add_argument('--runs',type=Path,nargs='+',required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();labels=json.loads(args.labels.read_text());results=[]
    for path in args.runs:
        run=json.loads(path.read_text());results.append(dict(file=str(path),run_id=run['id'],analysis_mode=run['result'].get('analysis_mode','visual'),metrics=evaluate(run,labels)))
    payload=json.dumps(results,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(payload)
    print(payload)
