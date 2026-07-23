import express from 'express';
import cors from 'cors';
import { exec } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
app.use(cors());
app.use(express.json());

// Helper function to run the CLI command
function runCli(args: string[], inputStdin?: string): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      PYTHONPATH: 'src',
      REDRUM_AI_DB_PATH: path.resolve(__dirname, 'memory.db'),
    };
    
    // Safely escape arguments for the shell to prevent any injection vulnerability
    const escapedArgs = args.map(arg => {
      return `'${arg.replace(/'/g, "'\\''")}'`;
    }).join(' ');

    const command = `python3 ai_partner.py ${escapedArgs}`;
    
    const child = exec(command, { env, cwd: __dirname }, (error, stdout, stderr) => {
      resolve({
        stdout: stdout || '',
        stderr: stderr || '',
        code: error ? (error.code || 1) : 0
      });
    });

    if (inputStdin && child.stdin) {
      child.stdin.write(inputStdin);
      child.stdin.end();
    }
  });
}

// REST API Endpoints

// 1. Chat/Query
app.post('/api/query', async (req, res) => {
  const { query, mode, responseFormat } = req.body;
  if (!query) {
    return res.status(400).json({ error: 'Query is required' });
  }

  const args = ['query', query];
  if (mode) {
    args.push('--mode', mode);
  }
  if (responseFormat) {
    args.push('--response-format', responseFormat);
  }

  try {
    const result = await runCli(args);
    if (result.code !== 0) {
      return res.json({ success: false, error: result.stderr || result.stdout, response: '' });
    }
    res.json({ success: true, response: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message || 'Server error' });
  }
});

// 2. Task List
app.get('/api/tasks', async (req, res) => {
  try {
    const result = await runCli(['--json', 'task', 'list']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to fetch tasks' });
    }
    try {
      const tasks = JSON.parse(result.stdout);
      res.json(tasks);
    } catch {
      res.json([]);
    }
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 3. Task Intake
app.post('/api/task/intake', async (req, res) => {
  const { request, priority, acceptanceCriteria, dueDate } = req.body;
  if (!request) {
    return res.status(400).json({ error: 'Request is required' });
  }

  const args = ['task', 'intake', request];
  if (priority) {
    args.push('--priority', priority);
  }
  if (acceptanceCriteria) {
    args.push('--acceptance-criteria', acceptanceCriteria);
  }
  if (dueDate) {
    args.push('--due-date', dueDate);
  }

  try {
    const result = await runCli(args);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to create task' });
    }
    res.json({ success: true, message: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 4. Task Update
app.post('/api/task/update', async (req, res) => {
  const { id, status, notes, appendNotes } = req.body;
  if (id === undefined) {
    return res.status(400).json({ error: 'Task ID is required' });
  }

  const args = ['task', 'update', '--id', String(id)];
  if (status) {
    args.push('--status', status);
  }
  if (notes) {
    args.push('--notes', notes);
  }
  if (appendNotes) {
    args.push('--append-notes', appendNotes);
  }

  try {
    const result = await runCli(args);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to update task' });
    }
    res.json({ success: true, message: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 5. Memory Stats
app.get('/api/memory/stats', async (req, res) => {
  try {
    const result = await runCli(['--json', 'memory', 'stats']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to fetch memory stats' });
    }
    try {
      const stats = JSON.parse(result.stdout);
      res.json(stats);
    } catch {
      res.status(500).json({ error: 'Invalid stats JSON returned from CLI' });
    }
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 6. Memory Search
app.get('/api/memory/search', async (req, res) => {
  const { q } = req.query;
  if (!q) {
    return res.status(400).json({ error: 'Query term q is required' });
  }

  try {
    const result = await runCli(['memory', 'search', String(q)]);
    res.json({ results: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 7. Memory Insert
app.post('/api/memory/insert', async (req, res) => {
  const { name, content, tags, sourceUri } = req.body;
  if (!name || !content) {
    return res.status(400).json({ error: 'Name and content are required' });
  }

  const args = ['memory', 'insert', '--name', name, '--content', content];
  if (tags) {
    args.push('--tags', tags);
  }
  if (sourceUri) {
    args.push('--source-uri', sourceUri);
  }

  try {
    const result = await runCli(args);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to insert memory' });
    }
    res.json({ success: true, message: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 8. Memory Delete
app.post('/api/memory/delete', async (req, res) => {
  const { id, type } = req.body;
  if (!id) {
    return res.status(400).json({ error: 'ID is required' });
  }

  const args = ['memory', 'delete', '--id', String(id)];
  if (type) {
    args.push('--type', type);
  }

  try {
    const result = await runCli(args);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to delete memory' });
    }
    res.json({ success: true });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 9. Memory Consolidate
app.post('/api/memory/consolidate', async (req, res) => {
  try {
    const result = await runCli(['memory', 'consolidate']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to consolidate memory' });
    }
    res.json({ success: true, message: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 10. Proactive Briefing
app.get('/api/proactive/briefing', async (req, res) => {
  try {
    const result = await runCli(['proactive', 'briefing']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Failed to generate briefing' });
    }
    res.json({ briefing: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 11. Proactive Predict Next Command
app.get('/api/proactive/predict', async (req, res) => {
  const { q } = req.query;
  if (!q) {
    return res.status(400).json({ error: 'Last command q is required' });
  }
  try {
    const result = await runCli(['proactive', 'predict', String(q)]);
    res.json({ suggestion: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 12. Proactive Draft Commit Message
app.post('/api/proactive/draft-commit', async (req, res) => {
  try {
    const result = await runCli(['proactive', 'draft-commit']);
    res.json({ draft: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 13. Health Check
app.get('/api/health', async (req, res) => {
  try {
    const result = await runCli(['health', '--skip-ollama-check']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Health check command failed' });
    }
    try {
      const data = JSON.parse(result.stdout);
      res.json(data);
    } catch {
      res.status(500).json({ error: 'Invalid health JSON returned from CLI' });
    }
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 14. Metrics
app.get('/api/metrics', async (req, res) => {
  try {
    const result = await runCli(['metrics']);
    if (result.code !== 0) {
      return res.status(500).json({ error: result.stderr || 'Metrics command failed' });
    }
    try {
      const data = JSON.parse(result.stdout);
      res.json(data);
    } catch {
      res.status(500).json({ error: 'Invalid metrics JSON returned from CLI' });
    }
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// 15. IT Partner Commands SRE
app.post('/api/it-partner', async (req, res) => {
  const { domain, task } = req.body;
  if (!domain || !task) {
    return res.status(400).json({ error: 'Domain and task are required' });
  }
  try {
    const result = await runCli(['it-partner', '--domain', domain, task]);
    res.json({ output: result.stdout.trim() });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Serve frontend SPA or integrate Vite middleware
const isProd = process.env.NODE_ENV === 'production';
const PORT = 3000;

if (!isProd) {
  const { createServer: createViteServer } = await import('vite');
  const vite = await createViteServer({
    server: { middlewareMode: true },
    appType: 'spa',
  });
  app.use(vite.middlewares);
} else {
  app.use(express.static(path.join(__dirname, 'dist')));
  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'dist', 'index.html'));
  });
}

app.listen(PORT, () => {
  console.log(`[redrum-ai-web] Server running on http://localhost:${PORT}`);
});
