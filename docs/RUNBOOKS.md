# Operational Runbooks

## 1. Database Corrupted
**Symptoms**: SQLite `disk I/O error` or `database disk image is malformed`.
**Action**:
1. Stop the application.
2. `cd ~/.gemini`
3. Copy the corrupted database: `cp memory.db memory.db.corrupted`
4. Restore from backup or re-bootstrap: `redrum-ai bootstrap`

## 2. Ollama Endpoint Unreachable
**Symptoms**: Timeout errors or `Connection refused` when invoking `redrum-ai`.
**Action**:
1. Check if Ollama is running: `systemctl status ollama` or `ps aux | grep ollama`
2. Start Ollama if stopped.
3. Verify the model is downloaded: `ollama list`
4. If running remotely, verify `OLLAMA_URL` environment variable.

## 3. High Latency
**Symptoms**: Commands take a very long time to return a plan or text.
**Action**:
1. Run `redrum-ai metrics` to see if the delay is in retrieval or model generation.
2. If retrieval is slow, you may need to prune `knowledge_bases`.
3. If model generation is slow, verify GPU utilization.
