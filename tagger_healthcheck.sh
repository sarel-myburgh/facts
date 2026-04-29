#!/bin/bash
# Only output if between 6am-9pm Cambodia time
HOUR=$(TZ=Asia/Phnom_Penh date +%H)
HOUR=${HOUR#0}  # strip leading zero

if [ "$HOUR" -lt 6 ] || [ "$HOUR" -ge 21 ]; then
    # Silent period — still do the work but produce NO output
    cd /home/sarel/projects/facts
    RUNNING=$(ps aux | grep "tag_facts.py" | grep -v grep | wc -l)
    if [ "$RUNNING" -eq 0 ]; then
        nohup bash run_tag_loop.sh >> logs/tag_loop.log 2>&1 &
    fi
    exit 0
fi

# Daytime — full output
cd /home/sarel/projects/facts

RESTARTED=""
RUNNING=$(ps aux | grep "tag_facts.py" | grep -v grep | wc -l)
if [ "$RUNNING" -eq 0 ]; then
    nohup bash run_tag_loop.sh >> logs/tag_loop.log 2>&1 &
    RESTARTED="RESTARTED | "
    sleep 2
fi

python3 -c "
import json
c = open('logs/current_file.txt').read().strip()
f = c.split('/')[-1]
d = json.load(open(c))
t = set(line.strip() for line in open('logs/tagged_facts.log') if line.strip())
r = len(d['facts']) - len(t)
m = json.load(open('logs/manifest.json'))
done = sum(1 for v in m['months'].values() if v.get('tags'))
print(f'${RESTARTED}Current: {f} — {len(t)}/{len(d[\"facts\"])} ({r} left) | Overall: {done}/{len(m[\"months\"])} months')
"