while true; do
  OLLAMA_API="5d823362900c4f5084dafb5feb65167a.Lwp6sthJWM343VXvkhcjySVY" python3 tools/tag_facts.py
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date)] Completed a file, moving to next..."
  else
    echo "[$(date)] Script exited with code $EXIT_CODE, stopping."
    break
  fi
  sleep 2
done
