import React, { useState, useEffect, useRef } from 'react';
import { 
  Terminal, 
  MessageSquare, 
  CheckSquare, 
  Database, 
  Cpu, 
  Activity, 
  AlertTriangle, 
  ShieldAlert, 
  Send, 
  Plus, 
  RefreshCw, 
  Search, 
  Trash2, 
  Sparkles, 
  Briefcase, 
  Settings, 
  Clock, 
  BookOpen, 
  GitCommit, 
  ChevronRight,
  Server
} from 'lucide-react';

// Interfaces based on Python types
interface Task {
  id: number;
  title: string;
  objective: string;
  status: 'backlog' | 'ready' | 'in_progress' | 'blocked' | 'needs_review' | 'done';
  priority: 'low' | 'medium' | 'high' | 'critical';
  session_notes?: string;
  created_at?: string;
  due_date?: string;
  acceptance_criteria?: string;
}

interface MemoryStats {
  project_slug: string;
  conversations: number;
  knowledge_bases: number;
  memory_facts: number;
  tasks: number;
  summaries: number;
  reviews: number;
  sessions: number;
  fact_status: Record<string, number>;
  scope: Record<string, any>;
}

interface ChatMessage {
  sender: 'user' | 'agent' | 'system';
  text: string;
  timestamp: string;
  mode?: string;
  format?: string;
}

interface SystemHealth {
  timestamp: string;
  database: {
    path: string;
    status: string;
    errors: string[];
  };
  ollama: {
    url: string;
    model: string;
    provider: string;
    status: string;
    errors: string[];
  };
  plugin: {
    api_version: string;
    capability_count: number;
    status: string;
    errors: string[];
  };
}

interface SystemMetrics {
  tasks: Record<string, any>;
  tools: {
    invocations: number;
    failures: number;
  };
  events: {
    total: number;
    by_type: Record<string, number>;
    by_severity: Record<string, number>;
  };
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'chat' | 'tasks' | 'memory' | 'sre' | 'diagnostics'>('chat');
  
  // Chat States
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'chat' | 'planning' | 'execution' | 'review'>('chat');
  const [responseFormat, setResponseFormat] = useState<'concise' | 'plan' | 'report'>('concise');
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  
  // Task States
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskLoading, setTaskLoading] = useState(false);
  const [newTaskRequest, setNewTaskRequest] = useState('');
  const [newTaskPriority, setNewTaskPriority] = useState<'low' | 'medium' | 'high' | 'critical'>('medium');
  const [newTaskCriteria, setNewTaskCriteria] = useState('');
  const [newTaskDueDate, setNewTaskDueDate] = useState('');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [taskNotesUpdate, setTaskNotesUpdate] = useState('');
  const [taskAppendMode, setTaskAppendMode] = useState(false);

  // Memory States
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [memorySearchQuery, setMemorySearchQuery] = useState('');
  const [memorySearchResults, setMemorySearchResults] = useState<string>('');
  const [newMemoryName, setNewMemoryName] = useState('');
  const [newMemoryContent, setNewMemoryContent] = useState('');
  const [newMemoryTags, setNewMemoryTags] = useState('');
  const [newMemorySource, setNewMemorySource] = useState('');
  const [memoryActionLoading, setMemoryActionLoading] = useState(false);

  // SRE States
  const [sreDomain, setSreDomain] = useState('sre');
  const [sreTask, setSreTask] = useState('');
  const [sreOutput, setSreOutput] = useState('');
  const [sreLoading, setSreLoading] = useState(false);

  // Diagnostics & Proactive States
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [briefing, setBriefing] = useState('');
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [commitDraft, setCommitDraft] = useState('');
  const [commitLoading, setCommitLoading] = useState(false);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Initial Fetching
  useEffect(() => {
    fetchHealthAndMetrics();
    fetchTasks();
    fetchMemoryStats();
    
    // Add greetings to Chat
    setChatHistory([
      {
        sender: 'system',
        text: 'Initialized local episodic and semantic memory engines. Standing by to partner on tasks, plans, and SRE operations.',
        timestamp: new Date().toLocaleTimeString()
      }
    ]);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, chatLoading]);

  const fetchHealthAndMetrics = async () => {
    setDiagnosticsLoading(true);
    try {
      const hRes = await fetch('/api/health');
      if (hRes.ok) setHealth(await hRes.json());
      
      const mRes = await fetch('/api/metrics');
      if (mRes.ok) setMetrics(await mRes.json());
    } catch (err) {
      console.error('Error fetching health/metrics:', err);
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  const fetchTasks = async () => {
    setTaskLoading(true);
    try {
      const res = await fetch('/api/tasks');
      if (res.ok) {
        const data = await res.json();
        setTasks(data);
      }
    } catch (err) {
      console.error('Error fetching tasks:', err);
    } finally {
      setTaskLoading(false);
    }
  };

  const fetchMemoryStats = async () => {
    try {
      const res = await fetch('/api/memory/stats');
      if (res.ok) setMemoryStats(await res.json());
    } catch (err) {
      console.error('Error fetching memory stats:', err);
    }
  };

  // Chat Actions
  const handleSendQuery = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    const userMsg: ChatMessage = {
      sender: 'user',
      text: query,
      timestamp: new Date().toLocaleTimeString(),
      mode,
      format: responseFormat
    };

    setChatHistory(prev => [...prev, userMsg]);
    const currentQuery = query;
    setQuery('');
    setChatLoading(true);

    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: currentQuery,
          mode,
          responseFormat
        })
      });

      const data = await res.json();
      if (data.success) {
        setChatHistory(prev => [...prev, {
          sender: 'agent',
          text: data.response,
          timestamp: new Date().toLocaleTimeString()
        }]);
      } else {
        setChatHistory(prev => [...prev, {
          sender: 'system',
          text: `Execution failed: ${data.error || 'Unknown server error'}`,
          timestamp: new Date().toLocaleTimeString()
        }]);
      }
    } catch (err: any) {
      setChatHistory(prev => [...prev, {
        sender: 'system',
        text: `Network failure: ${err.message}`,
        timestamp: new Date().toLocaleTimeString()
      }]);
    } finally {
      setChatLoading(false);
      // Refresh background states that might have updated
      fetchTasks();
      fetchMemoryStats();
    }
  };

  // Task Actions
  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskRequest.trim()) return;

    setTaskLoading(true);
    try {
      const res = await fetch('/api/task/intake', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request: newTaskRequest,
          priority: newTaskPriority,
          acceptanceCriteria: newTaskCriteria || undefined,
          dueDate: newTaskDueDate || undefined
        })
      });

      if (res.ok) {
        setNewTaskRequest('');
        setNewTaskCriteria('');
        setNewTaskDueDate('');
        await fetchTasks();
      }
    } catch (err) {
      console.error('Error creating task:', err);
    } finally {
      setTaskLoading(false);
    }
  };

  const handleUpdateTaskStatus = async (taskId: number, newStatus: Task['status']) => {
    try {
      const res = await fetch('/api/task/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: taskId,
          status: newStatus
        })
      });

      if (res.ok) {
        await fetchTasks();
        if (selectedTask && selectedTask.id === taskId) {
          setSelectedTask(prev => prev ? { ...prev, status: newStatus } : null);
        }
      }
    } catch (err) {
      console.error('Error updating task status:', err);
    }
  };

  const handleUpdateTaskNotes = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTask) return;

    try {
      const res = await fetch('/api/task/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedTask.id,
          notes: !taskAppendMode ? taskNotesUpdate : undefined,
          appendNotes: taskAppendMode ? taskNotesUpdate : undefined
        })
      });

      if (res.ok) {
        setTaskNotesUpdate('');
        await fetchTasks();
        // Refresh selected task info
        const updatedRes = await fetch('/api/tasks');
        if (updatedRes.ok) {
          const allTasks: Task[] = await updatedRes.json();
          const found = allTasks.find(t => t.id === selectedTask.id);
          if (found) setSelectedTask(found);
        }
      }
    } catch (err) {
      console.error('Error updating task notes:', err);
    }
  };

  // Memory Actions
  const handleMemorySearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memorySearchQuery.trim()) return;

    setMemoryActionLoading(true);
    try {
      const res = await fetch(`/api/memory/search?q=${encodeURIComponent(memorySearchQuery)}`);
      if (res.ok) {
        const data = await res.json();
        setMemorySearchResults(data.results || 'No matching memories found.');
      }
    } catch (err) {
      setMemorySearchResults('Error querying semantic index.');
    } finally {
      setMemoryActionLoading(false);
    }
  };

  const handleInsertMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMemoryName.trim() || !newMemoryContent.trim()) return;

    setMemoryActionLoading(true);
    try {
      const res = await fetch('/api/memory/insert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newMemoryName,
          content: newMemoryContent,
          tags: newMemoryTags || undefined,
          sourceUri: newMemorySource || undefined
        })
      });

      if (res.ok) {
        setNewMemoryName('');
        setNewMemoryContent('');
        setNewMemoryTags('');
        setNewMemorySource('');
        await fetchMemoryStats();
      }
    } catch (err) {
      console.error('Error inserting memory:', err);
    } finally {
      setMemoryActionLoading(false);
    }
  };

  const handleConsolidateMemory = async () => {
    setMemoryActionLoading(true);
    try {
      const res = await fetch('/api/memory/consolidate', { method: 'POST' });
      if (res.ok) {
        alert('Memory consolidation run finished successfully!');
        await fetchMemoryStats();
      }
    } catch (err) {
      alert('Failed to trigger memory consolidation.');
    } finally {
      setMemoryActionLoading(false);
    }
  };

  const handleDeleteMemory = async (id: string, type: 'knowledge' | 'fact') => {
    if (!confirm('Are you sure you want to delete this memory record?')) return;

    setMemoryActionLoading(true);
    try {
      const res = await fetch('/api/memory/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, type })
      });

      if (res.ok) {
        await fetchMemoryStats();
        if (memorySearchQuery) {
          // Re-trigger search to update view
          const searchRes = await fetch(`/api/memory/search?q=${encodeURIComponent(memorySearchQuery)}`);
          if (searchRes.ok) {
            const data = await searchRes.json();
            setMemorySearchResults(data.results);
          }
        }
      }
    } catch (err) {
      console.error('Error deleting memory:', err);
    } finally {
      setMemoryActionLoading(false);
    }
  };

  // SRE Actions
  const handleExecuteSreTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sreTask.trim()) return;

    setSreLoading(true);
    setSreOutput('');
    try {
      const res = await fetch('/api/it-partner', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: sreDomain,
          task: sreTask
        })
      });

      if (res.ok) {
        const data = await res.json();
        setSreOutput(data.output || 'No output received.');
      } else {
        const data = await res.json();
        setSreOutput(`Error: ${data.error || 'Execution failed'}`);
      }
    } catch (err: any) {
      setSreOutput(`Network error: ${err.message}`);
    } finally {
      setSreLoading(false);
    }
  };

  // Proactive Actions
  const handleGenerateBriefing = async () => {
    setBriefingLoading(true);
    setBriefing('');
    try {
      const res = await fetch('/api/proactive/briefing');
      if (res.ok) {
        const data = await res.json();
        setBriefing(data.briefing);
      }
    } catch (err) {
      console.error('Error generating briefing:', err);
    } finally {
      setBriefingLoading(false);
    }
  };

  const handleDraftCommit = async () => {
    setCommitLoading(true);
    setCommitDraft('');
    try {
      const res = await fetch('/api/proactive/draft-commit', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setCommitDraft(data.draft);
      }
    } catch (err) {
      console.error('Error drafting commit:', err);
    } finally {
      setCommitLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#07080d] text-slate-100 font-sans overflow-hidden" id="applet-viewport">
      
      {/* Sidebar Navigation */}
      <aside className="w-80 bg-[#0c0e17] border-r border-[#1a1c29] flex flex-col justify-between" id="applet-sidebar">
        <div>
          {/* Header */}
          <div className="p-6 border-b border-[#1a1c29] flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded bg-red-600/10 border border-red-500/30 flex items-center justify-center shadow-[0_0_15px_rgba(239,68,68,0.15)]">
                <Terminal className="w-4 h-4 text-red-500" />
              </div>
              <div>
                <h1 className="font-mono text-lg font-bold tracking-wider text-slate-50">REDRUM // AI</h1>
                <p className="text-[10px] font-mono text-red-400 tracking-widest uppercase">Companion Node</p>
              </div>
            </div>
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-green-500/10 border border-green-500/20">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
              <span className="text-[9px] font-mono font-bold text-green-400 uppercase tracking-wider">ACTIVE</span>
            </div>
          </div>

          {/* Nav List */}
          <nav className="p-4 space-y-1.5">
            <button 
              id="nav-chat"
              onClick={() => setActiveTab('chat')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'chat' 
                  ? 'bg-red-500/10 border border-red-500/20 text-red-400' 
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-3">
                <MessageSquare className="w-4.5 h-4.5" />
                <span>Direct Partner Chat</span>
              </div>
              <ChevronRight className="w-4 h-4 opacity-50" />
            </button>

            <button 
              id="nav-tasks"
              onClick={() => setActiveTab('tasks')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'tasks' 
                  ? 'bg-red-500/10 border border-red-500/20 text-red-400' 
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-3">
                <CheckSquare className="w-4.5 h-4.5" />
                <span>Active Task Board</span>
              </div>
              <ChevronRight className="w-4 h-4 opacity-50" />
            </button>

            <button 
              id="nav-memory"
              onClick={() => setActiveTab('memory')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'memory' 
                  ? 'bg-red-500/10 border border-red-500/20 text-red-400' 
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-3">
                <Database className="w-4.5 h-4.5" />
                <span>Memory & Context</span>
              </div>
              <ChevronRight className="w-4 h-4 opacity-50" />
            </button>

            <button 
              id="nav-sre"
              onClick={() => setActiveTab('sre')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'sre' 
                  ? 'bg-red-500/10 border border-red-500/20 text-red-400' 
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-3">
                <Cpu className="w-4.5 h-4.5" />
                <span>IT/SRE Ops Desk</span>
              </div>
              <ChevronRight className="w-4 h-4 opacity-50" />
            </button>

            <button 
              id="nav-diagnostics"
              onClick={() => setActiveTab('diagnostics')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm font-medium transition-all ${
                activeTab === 'diagnostics' 
                  ? 'bg-red-500/10 border border-red-500/20 text-red-400' 
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/40'
              }`}
            >
              <div className="flex items-center gap-3">
                <Activity className="w-4.5 h-4.5" />
                <span>Diagnostics & Metrics</span>
              </div>
              <ChevronRight className="w-4 h-4 opacity-50" />
            </button>
          </nav>
        </div>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-[#1a1c29] bg-[#090b12]" id="sidebar-footer">
          <div className="flex items-center justify-between text-[11px] font-mono text-slate-500 mb-2">
            <span>DATABASE TYPE</span>
            <span className="text-slate-300 font-semibold">SQLite + LanceDB</span>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
            <span>DB SCOPE</span>
            <span className="text-slate-300 font-semibold">redrum-ai (Local)</span>
          </div>
        </div>
      </aside>

      {/* Main Panel Content */}
      <main className="flex-1 flex flex-col bg-[#07080d] overflow-hidden" id="applet-main">
        
        {/* Top bar with environment info */}
        <header className="h-14 bg-[#0a0c14] border-b border-[#131522] px-8 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-xs font-mono font-bold text-slate-400 uppercase tracking-widest">
              {activeTab.toUpperCase()} VIEW
            </span>
            <div className="h-4 w-[1px] bg-slate-800"></div>
            <span className="text-xs text-slate-500 flex items-center gap-1.5 font-mono">
              <Server className="w-3.5 h-3.5 text-slate-600" />
              <span>Host Port: 3000</span>
            </span>
          </div>

          <div className="flex items-center gap-4">
            <button 
              onClick={fetchHealthAndMetrics}
              disabled={diagnosticsLoading}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-100 transition-colors"
              title="Refresh status"
            >
              <RefreshCw className={`w-4 h-4 ${diagnosticsLoading ? 'animate-spin' : ''}`} />
            </button>
            <div className="text-right">
              <div className="text-[11px] font-mono text-slate-400 font-semibold">SQLite Ready</div>
              <div className="text-[9px] font-mono text-slate-600 uppercase">./memory.db</div>
            </div>
          </div>
        </header>

        {/* Tab Contents */}
        <div className="flex-1 overflow-y-auto p-8" id="view-container">

          {/* CHAT TAB */}
          {activeTab === 'chat' && (
            <div className="h-full flex flex-col max-w-4xl mx-auto" id="chat-view">
              {/* Configuration panel */}
              <div className="grid grid-cols-2 gap-4 mb-6 bg-[#0c0e17] p-4 rounded-xl border border-[#1a1c29]">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Interaction Mode</label>
                  <select 
                    value={mode} 
                    onChange={(e) => setMode(e.target.value as any)}
                    className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-200 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50"
                  >
                    <option value="chat">Direct Dialog (Chat)</option>
                    <option value="planning">Milestone Planning</option>
                    <option value="execution">Execution & Commands</option>
                    <option value="review">Work Review</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Response Formatting</label>
                  <select 
                    value={responseFormat} 
                    onChange={(e) => setResponseFormat(e.target.value as any)}
                    className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-200 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50"
                  >
                    <option value="concise">Concise Assistant</option>
                    <option value="plan">Structured Outline / Plan</option>
                    <option value="report">Detailed Deliverable Report</option>
                  </select>
                </div>
              </div>

              {/* Chat Stream */}
              <div className="flex-1 bg-[#090a10] border border-[#131522] rounded-xl p-6 overflow-y-auto mb-4 flex flex-col space-y-4">
                {chatHistory.map((msg, i) => (
                  <div 
                    key={i} 
                    className={`flex flex-col max-w-[85%] ${
                      msg.sender === 'user' ? 'self-end items-end' : 'self-start items-start'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-mono text-slate-500">{msg.timestamp}</span>
                      {msg.mode && (
                        <span className="text-[9px] font-mono bg-red-950/40 border border-red-900/30 text-red-400 px-1.5 py-0.25 rounded uppercase">
                          {msg.mode}
                        </span>
                      )}
                    </div>
                    <div 
                      className={`rounded-xl px-4.5 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                        msg.sender === 'user' 
                          ? 'bg-red-600/10 border border-red-500/30 text-slate-200 rounded-tr-none' 
                          : msg.sender === 'system'
                          ? 'bg-slate-900/80 border border-slate-800 text-slate-400 font-mono text-xs'
                          : 'bg-[#0f111a] border border-[#1a1c29] text-slate-200 rounded-tl-none'
                      }`}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div className="self-start flex items-center gap-2.5 bg-[#0f111a] border border-[#1a1c29] rounded-xl rounded-tl-none px-4 py-3">
                    <div className="flex space-x-1.5">
                      <div className="w-2 h-2 rounded-full bg-red-500 animate-bounce" style={{ animationDelay: '0ms' }}></div>
                      <div className="w-2 h-2 rounded-full bg-red-500 animate-bounce" style={{ animationDelay: '150ms' }}></div>
                      <div className="w-2 h-2 rounded-full bg-red-500 animate-bounce" style={{ animationDelay: '300ms' }}></div>
                    </div>
                    <span className="text-xs font-mono text-slate-400">Consulting memory database...</span>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Chat Input */}
              <form onSubmit={handleSendQuery} className="flex gap-3" id="chat-input-form">
                <input 
                  type="text" 
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={`Send query to AI partner (Active Mode: ${mode})...`}
                  disabled={chatLoading}
                  className="flex-1 bg-[#090b11] border border-[#1a1c29] text-slate-100 rounded-xl px-4.5 py-3.5 text-sm focus:outline-none focus:border-red-500/60 placeholder-slate-600 transition-colors"
                />
                <button 
                  type="submit" 
                  disabled={chatLoading}
                  className="px-5 bg-red-600/90 hover:bg-red-600 border border-red-500/20 rounded-xl font-medium text-sm flex items-center justify-center gap-2 text-slate-50 cursor-pointer shadow-[0_0_15px_rgba(220,38,38,0.1)] hover:shadow-[0_0_20px_rgba(220,38,38,0.2)] active:scale-98 transition-all disabled:opacity-50 disabled:pointer-events-none"
                >
                  <Send className="w-4.5 h-4.5" />
                  <span>Execute</span>
                </button>
              </form>
            </div>
          )}

          {/* ACTIVE TASKS TAB */}
          {activeTab === 'tasks' && (
            <div className="grid grid-cols-3 gap-8 h-full max-w-7xl mx-auto" id="tasks-view">
              
              {/* Task Intake Form */}
              <div className="col-span-1 bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 flex flex-col gap-5 h-fit shadow-md">
                <div className="border-b border-[#1d2030] pb-4">
                  <h2 className="text-md font-semibold tracking-wider flex items-center gap-2">
                    <Plus className="w-5 h-5 text-red-500" />
                    <span>Task Intake Engine</span>
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">Submit a natural language project request to register a structured task.</p>
                </div>

                <form onSubmit={handleCreateTask} className="space-y-4">
                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Natural Language Request</label>
                    <textarea 
                      value={newTaskRequest}
                      onChange={(e) => setNewTaskRequest(e.target.value)}
                      placeholder="e.g., Run a comprehensive system backup and audit script"
                      rows={4}
                      className="w-full bg-[#131522] border border-[#1e2235] text-slate-100 rounded-lg p-3 text-sm focus:outline-none focus:border-red-500/50 placeholder-slate-600"
                      required
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Priority Assessment</label>
                    <div className="grid grid-cols-4 gap-2">
                      {(['low', 'medium', 'high', 'critical'] as const).map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => setNewTaskPriority(p)}
                          className={`py-1.5 text-xs font-mono font-bold rounded border capitalize ${
                            newTaskPriority === p
                              ? 'bg-red-500/10 border-red-500/40 text-red-400'
                              : 'bg-slate-900/50 border-slate-800 text-slate-400 hover:bg-slate-850'
                          }`}
                        >
                          {p}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Explicit Acceptance Criteria</label>
                    <input 
                      type="text"
                      value={newTaskCriteria}
                      onChange={(e) => setNewTaskCriteria(e.target.value)}
                      placeholder="Specify clear metric of completion"
                      className="w-full bg-[#131522] border border-[#1e2235] text-slate-100 rounded-lg p-2.5 text-sm focus:outline-none focus:border-red-500/50 placeholder-slate-600"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Due Date / Timeout</label>
                    <input 
                      type="text"
                      value={newTaskDueDate}
                      onChange={(e) => setNewTaskDueDate(e.target.value)}
                      placeholder="e.g., 2026-07-25"
                      className="w-full bg-[#131522] border border-[#1e2235] text-slate-100 rounded-lg p-2.5 text-sm focus:outline-none focus:border-red-500/50 placeholder-slate-600"
                    />
                  </div>

                  <button 
                    type="submit"
                    className="w-full py-2.5 bg-red-600 hover:bg-red-500 text-slate-50 font-medium text-sm rounded-lg flex items-center justify-center gap-2 cursor-pointer shadow-[0_0_15px_rgba(220,38,38,0.15)] hover:shadow-[0_0_20px_rgba(220,38,38,0.2)] hover:scale-[1.01] transition-all"
                  >
                    <Plus className="w-4 h-4" />
                    <span>Create structured task</span>
                  </button>
                </form>
              </div>

              {/* Task Board / List */}
              <div className="col-span-2 flex flex-col gap-6">
                
                {/* Search / Filter Bar */}
                <div className="flex items-center justify-between bg-[#0c0e17] border border-[#1a1c29] px-6 py-4 rounded-xl">
                  <div className="flex items-center gap-3">
                    <CheckSquare className="w-5 h-5 text-red-500" />
                    <div>
                      <h3 className="font-semibold text-sm">Active Task Repository</h3>
                      <p className="text-xs text-slate-400">Manage structure, notes, and milestones of ongoing plans.</p>
                    </div>
                  </div>
                  <button 
                    onClick={fetchTasks}
                    disabled={taskLoading}
                    className="flex items-center gap-2 text-xs font-mono bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 py-1.5 px-3 rounded-lg"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${taskLoading ? 'animate-spin' : ''}`} />
                    <span>Sync Database</span>
                  </button>
                </div>

                {/* Tasks List */}
                <div className="space-y-3.5 max-h-[600px] overflow-y-auto pr-2">
                  {tasks.length === 0 ? (
                    <div className="bg-[#0c0e17]/50 border border-dashed border-[#1a1c29] p-12 text-center rounded-xl">
                      <CheckSquare className="w-10 h-10 text-slate-600 mx-auto mb-3" />
                      <p className="text-slate-400 text-sm">No active tasks in scope.</p>
                      <p className="text-xs text-slate-500 mt-1">Submit a query above to intake tasks automatically.</p>
                    </div>
                  ) : (
                    tasks.map((task) => (
                      <div 
                        key={task.id}
                        className={`bg-[#0c0e17] border rounded-xl p-5 hover:border-slate-700/80 transition-all ${
                          selectedTask?.id === task.id ? 'border-red-500/40' : 'border-[#1a1c29]'
                        }`}
                      >
                        <div className="flex items-start justify-between">
                          <div className="cursor-pointer flex-1" onClick={() => setSelectedTask(task)}>
                            <div className="flex items-center gap-2.5 mb-1.5">
                              <span className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded ${
                                task.priority === 'critical' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                task.priority === 'high' ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' :
                                task.priority === 'medium' ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20' :
                                'bg-slate-950/60 text-slate-400 border border-slate-800'
                              }`}>
                                {task.priority}
                              </span>
                              <span className="text-xs font-mono text-slate-500">ID: #{task.id}</span>
                            </div>
                            <h4 className="font-bold text-slate-200 text-sm hover:text-red-400 transition-colors">{task.title}</h4>
                            <p className="text-xs text-slate-400 mt-1">{task.objective}</p>
                          </div>

                          {/* Status select dropdown */}
                          <select
                            value={task.status}
                            onChange={(e) => handleUpdateTaskStatus(task.id, e.target.value as any)}
                            className={`text-xs font-mono font-bold uppercase rounded px-2.5 py-1.5 border focus:outline-none ${
                              task.status === 'done' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                              task.status === 'blocked' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                              task.status === 'in_progress' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                              'bg-slate-950/50 text-slate-300 border-slate-800'
                            }`}
                          >
                            <option value="backlog">Backlog</option>
                            <option value="ready">Ready</option>
                            <option value="in_progress">In Progress</option>
                            <option value="blocked">Blocked</option>
                            <option value="needs_review">Needs Review</option>
                            <option value="done">Done</option>
                          </select>
                        </div>

                        {/* Expandable Session notes editor */}
                        {selectedTask?.id === task.id && (
                          <div className="mt-4 pt-4 border-t border-[#1d2030] space-y-3 bg-[#090a10] p-4 rounded-lg">
                            <div>
                              <h5 className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Acceptance Criteria</h5>
                              <p className="text-xs text-slate-300 mt-1">{task.acceptance_criteria || 'None specified.'}</p>
                            </div>
                            
                            <div>
                              <h5 className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Active Session Notes</h5>
                              <pre className="text-xs text-slate-400 mt-1.5 whitespace-pre-wrap font-mono p-3 bg-slate-950/60 rounded border border-slate-900/60 leading-relaxed">
                                {task.session_notes || '(No session notes yet. Record details below.)'}
                              </pre>
                            </div>

                            <form onSubmit={handleUpdateTaskNotes} className="space-y-2">
                              <div className="flex items-center justify-between">
                                <label className="text-[10px] font-mono text-slate-400 uppercase">Write or Append Notes</label>
                                <div className="flex items-center gap-2">
                                  <span className="text-[10px] font-mono text-slate-500">Append Mode</span>
                                  <input 
                                    type="checkbox" 
                                    checked={taskAppendMode} 
                                    onChange={(e) => setTaskAppendMode(e.target.checked)} 
                                    className="accent-red-500"
                                  />
                                </div>
                              </div>
                              <div className="flex gap-2">
                                <input 
                                  type="text"
                                  value={taskNotesUpdate}
                                  onChange={(e) => setTaskNotesUpdate(e.target.value)}
                                  placeholder={taskAppendMode ? "Append details to current session logs..." : "Overwrite session notes..."}
                                  className="flex-1 bg-slate-950/80 border border-slate-800 text-slate-100 rounded p-2 text-xs focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                                />
                                <button 
                                  type="submit"
                                  className="bg-slate-900 border border-slate-800 hover:bg-slate-850 px-3 py-2 text-xs font-mono font-bold rounded text-slate-200 hover:text-white"
                                >
                                  Save Notes
                                </button>
                              </div>
                            </form>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          {/* MEMORY & CONTEXT TAB */}
          {activeTab === 'memory' && (
            <div className="grid grid-cols-3 gap-8 h-full max-w-7xl mx-auto" id="memory-view">
              
              {/* Memory Stats / Actions Column */}
              <div className="col-span-1 space-y-6">
                
                {/* Statistics Card */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                  <div className="flex items-center justify-between border-b border-[#1d2030] pb-3.5 mb-4">
                    <h4 className="font-semibold text-sm tracking-wider flex items-center gap-2">
                      <Database className="w-5 h-5 text-red-500" />
                      <span>Memory Index Stats</span>
                    </h4>
                    <button 
                      onClick={fetchMemoryStats}
                      className="p-1 hover:bg-slate-800 rounded transition-colors text-slate-400 hover:text-slate-200"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {memoryStats ? (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="flex justify-between py-1 border-b border-slate-900/40">
                        <span className="text-slate-500">PROJECT</span>
                        <span className="text-slate-300 font-bold uppercase">{memoryStats.project_slug}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900/40">
                        <span className="text-slate-500">KNOWLEDGE RECORDS</span>
                        <span className="text-slate-300 font-bold">{memoryStats.knowledge_bases}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900/40">
                        <span className="text-slate-500">EPISODIC FACTS</span>
                        <span className="text-slate-300 font-bold">{memoryStats.memory_facts}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900/40">
                        <span className="text-slate-500">RAW TURNS STORED</span>
                        <span className="text-slate-300 font-bold">{memoryStats.conversations}</span>
                      </div>
                      <div className="flex justify-between py-1 border-b border-slate-900/40">
                        <span className="text-slate-500">SUMMARIES COMPILED</span>
                        <span className="text-slate-300 font-bold">{memoryStats.summaries}</span>
                      </div>
                      <div className="flex justify-between py-1">
                        <span className="text-slate-500">SESSIONS LOGGED</span>
                        <span className="text-slate-300 font-bold">{memoryStats.sessions}</span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Fetching statistics...</p>
                  )}
                </div>

                {/* Database Maintenance Daemon Controls */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                  <h4 className="font-semibold text-sm tracking-wider flex items-center gap-2 mb-2">
                    <Sparkles className="w-5 h-5 text-red-500" />
                    <span>Memory Consolidation</span>
                  </h4>
                  <p className="text-xs text-slate-400 mb-4.5">
                    Triggers the offline memory daemon to auto-cluster, index semantic nodes, analyze redundant records, and consolidate knowledge states.
                  </p>
                  <button 
                    onClick={handleConsolidateMemory}
                    disabled={memoryActionLoading}
                    className="w-full py-2.5 bg-slate-900 border border-slate-800 hover:bg-slate-850 text-slate-300 hover:text-white rounded-lg text-xs font-mono font-bold flex items-center justify-center gap-2 transition-all cursor-pointer disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${memoryActionLoading ? 'animate-spin' : ''}`} />
                    <span>Trigger Consolidation</span>
                  </button>
                </div>
              </div>

              {/* Memory Search & Manual Insertion */}
              <div className="col-span-2 space-y-6">
                
                {/* Search Memory Card */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 flex flex-col shadow-md">
                  <h4 className="font-semibold text-sm tracking-wider flex items-center gap-2 border-b border-[#1d2030] pb-3.5 mb-4">
                    <Search className="w-5 h-5 text-red-500" />
                    <span>Semantic Search Interface</span>
                  </h4>

                  <form onSubmit={handleMemorySearch} className="flex gap-3 mb-4">
                    <input 
                      type="text" 
                      value={memorySearchQuery}
                      onChange={(e) => setMemorySearchQuery(e.target.value)}
                      placeholder="Enter keywords or prompts to retrieve relevant facts..."
                      className="flex-1 bg-slate-950/80 border border-slate-800 text-sm text-slate-200 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50"
                    />
                    <button 
                      type="submit" 
                      disabled={memoryActionLoading}
                      className="px-4 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded-lg text-xs font-mono font-bold flex items-center gap-2 text-slate-300 cursor-pointer"
                    >
                      Search
                    </button>
                  </form>

                  {/* Results box */}
                  <div className="flex-1 min-h-[140px] max-h-[220px] overflow-y-auto bg-slate-950/70 border border-slate-900 rounded-lg p-4 font-mono text-xs text-slate-300 leading-relaxed">
                    {memorySearchResults ? (
                      <pre className="whitespace-pre-wrap">{memorySearchResults}</pre>
                    ) : (
                      <span className="text-slate-600">Retrieve semantic context nodes. Click search.</span>
                    )}
                  </div>
                </div>

                {/* Add Knowledge Entry Form */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                  <h4 className="font-semibold text-sm tracking-wider flex items-center gap-2 border-b border-[#1d2030] pb-3.5 mb-4">
                    <Plus className="w-5 h-5 text-red-500" />
                    <span>Insert Manual Knowledge Fact</span>
                  </h4>

                  <form onSubmit={handleInsertMemory} className="grid grid-cols-2 gap-4">
                    <div className="col-span-2">
                      <label className="block text-xs font-mono text-slate-400 mb-1 uppercase">Fact Title / Concept Name</label>
                      <input 
                        type="text" 
                        value={newMemoryName}
                        onChange={(e) => setNewMemoryName(e.target.value)}
                        placeholder="e.g., Redrum SSH configuration paths"
                        className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-100 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                        required
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-mono text-slate-400 mb-1 uppercase">Raw Text Content</label>
                      <textarea 
                        value={newMemoryContent}
                        onChange={(e) => setNewMemoryContent(e.target.value)}
                        placeholder="Define facts, configurations, API keys reference styles, preferences..."
                        rows={3}
                        className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-100 rounded-lg p-3 focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-mono text-slate-400 mb-1 uppercase">Tags (comma-separated)</label>
                      <input 
                        type="text" 
                        value={newMemoryTags}
                        onChange={(e) => setNewMemoryTags(e.target.value)}
                        placeholder="e.g., ssh, config, security"
                        className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-100 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-mono text-slate-400 mb-1 uppercase">Source URI</label>
                      <input 
                        type="text" 
                        value={newMemorySource}
                        onChange={(e) => setNewMemorySource(e.target.value)}
                        placeholder="e.g., ~/.ssh/config"
                        className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-100 rounded-lg py-2 px-3 focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                      />
                    </div>
                    <div className="col-span-2 mt-2">
                      <button 
                        type="submit"
                        disabled={memoryActionLoading}
                        className="w-full py-2.5 bg-red-600 hover:bg-red-500 text-slate-50 font-medium text-sm rounded-lg flex items-center justify-center gap-2 cursor-pointer transition-all shadow-[0_0_15px_rgba(220,38,38,0.15)] hover:shadow-[0_0_20px_rgba(220,38,38,0.2)]"
                      >
                        <Plus className="w-4 h-4" />
                        <span>Insert Memory Fact</span>
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
          )}

          {/* IT/SRE OPS DESK */}
          {activeTab === 'sre' && (
            <div className="max-w-4xl mx-auto space-y-6" id="sre-view">
              
              {/* Domain & Command Entry */}
              <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                <div className="border-b border-[#1d2030] pb-4 mb-5">
                  <h2 className="text-md font-semibold tracking-wider flex items-center gap-2.5">
                    <Cpu className="w-5 h-5 text-red-500" />
                    <span>Advanced IT Operations & SRE Engine</span>
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">
                    Execute diagnostics, review infrastructure models, run chaos routines, and analyze logs with specialized domain intelligence.
                  </p>
                </div>

                <form onSubmit={handleExecuteSreTask} className="space-y-4">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="col-span-1">
                      <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">SRE Domain Target</label>
                      <select 
                        value={sreDomain}
                        onChange={(e) => setSreDomain(e.target.value)}
                        className="w-full bg-[#131522] border border-[#1e2235] text-sm text-slate-200 rounded-lg py-2.5 px-3 focus:outline-none focus:border-red-500/50"
                      >
                        <option value="sre">SRE / Incident Post-Mortem</option>
                        <option value="k8s">Kubernetes Orchestration</option>
                        <option value="chaos">Chaos Engineering</option>
                        <option value="cicd">CI/CD Automation pipelines</option>
                        <option value="security">Infrastructure Hardening</option>
                        <option value="network">TCP & Routing Diagnostics</option>
                        <option value="os_kernel">Linux Kernel Tunings</option>
                      </select>
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-mono text-slate-400 mb-1.5 uppercase">Operations Command Prompt</label>
                      <input 
                        type="text"
                        value={sreTask}
                        onChange={(e) => setSreTask(e.target.value)}
                        placeholder="Define infrastructure audit target or incident context..."
                        className="w-full bg-[#131522] border border-[#1e2235] text-slate-100 rounded-lg p-2.5 text-sm focus:outline-none focus:border-red-500/50 placeholder-slate-700"
                        required
                      />
                    </div>
                  </div>

                  <button 
                    type="submit"
                    disabled={sreLoading}
                    className="w-full py-2.5 bg-red-600 hover:bg-red-500 text-slate-50 font-medium text-sm rounded-lg flex items-center justify-center gap-2 cursor-pointer transition-all disabled:opacity-50"
                  >
                    <Terminal className="w-4 h-4" />
                    <span>{sreLoading ? 'Analyzing infrastructure logs...' : 'Execute SRE Operations Command'}</span>
                  </button>
                </form>
              </div>

              {/* Console Output */}
              <div className="bg-slate-950 border border-slate-900 rounded-xl p-6 flex flex-col min-h-[300px]">
                <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-4 text-xs font-mono text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <Terminal className="w-3.5 h-3.5 text-red-500" />
                    <span>SRE CONSOLE OUTPUT</span>
                  </span>
                  <span>DOMAIN: {sreDomain.toUpperCase()}</span>
                </div>

                <div className="flex-1 font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap select-text">
                  {sreLoading ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-3">
                      <RefreshCw className="w-6 h-6 text-red-500 animate-spin" />
                      <p className="text-slate-500 text-xs">Executing domain playbook and consulting memory indexes...</p>
                    </div>
                  ) : sreOutput ? (
                    sreOutput
                  ) : (
                    <span className="text-slate-700">Infrastructure desk standing by. Run commands to stream output.</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* DIAGNOSTICS & METRICS TAB */}
          {activeTab === 'diagnostics' && (
            <div className="max-w-5xl mx-auto space-y-8" id="diagnostics-view">
              
              {/* Proactive Tools Deck */}
              <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                <h3 className="font-semibold text-md border-b border-[#1d2030] pb-3.5 mb-5 flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-red-500" />
                  <span>Proactive Autonomy Tools</span>
                </h3>

                <div className="grid grid-cols-2 gap-6">
                  {/* Daily briefing pane */}
                  <div className="bg-[#090a10] border border-[#1a1c29] rounded-lg p-5 flex flex-col justify-between">
                    <div>
                      <h4 className="font-bold text-sm text-slate-200">Daily Personalized Briefing</h4>
                      <p className="text-xs text-slate-400 mt-1 mb-4">
                        Consults tasks, history and memory stats to build a consolidated daily briefing of milestones.
                      </p>
                      {briefing && (
                        <div className="p-3 bg-slate-950/80 rounded border border-slate-900/60 text-xs font-mono text-slate-300 mb-4 whitespace-pre-wrap leading-relaxed max-h-[160px] overflow-y-auto">
                          {briefing}
                        </div>
                      )}
                    </div>
                    <button 
                      onClick={handleGenerateBriefing}
                      disabled={briefingLoading}
                      className="py-2 bg-slate-900 border border-slate-800 hover:bg-slate-850 text-slate-300 hover:text-white rounded font-mono font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer"
                    >
                      {briefingLoading ? 'Synthesizing...' : 'Generate Daily Briefing'}
                    </button>
                  </div>

                  {/* Git commit writer pane */}
                  <div className="bg-[#090a10] border border-[#1a1c29] rounded-lg p-5 flex flex-col justify-between">
                    <div>
                      <h4 className="font-bold text-sm text-slate-200">Git Commit Message Writer</h4>
                      <p className="text-xs text-slate-400 mt-1 mb-4">
                        Scans the workspace git changes and drafts a perfectly formatted semantic commit message.
                      </p>
                      {commitDraft && (
                        <div className="p-3 bg-slate-950/80 rounded border border-slate-900/60 text-xs font-mono text-slate-300 mb-4 whitespace-pre-wrap leading-relaxed max-h-[160px] overflow-y-auto">
                          {commitDraft}
                        </div>
                      )}
                    </div>
                    <button 
                      onClick={handleDraftCommit}
                      disabled={commitLoading}
                      className="py-2 bg-slate-900 border border-slate-800 hover:bg-slate-850 text-slate-300 hover:text-white rounded font-mono font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer"
                    >
                      {commitLoading ? 'Reviewing diffs...' : 'Draft Git Commit Message'}
                    </button>
                  </div>
                </div>
              </div>

              {/* Health Grid */}
              <div className="grid grid-cols-2 gap-8">
                
                {/* System Diagnostics */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                  <h3 className="font-semibold text-sm border-b border-[#1d2030] pb-3.5 mb-4 flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <Cpu className="w-5 h-5 text-red-500" />
                      <span>Diagnostics Diagnostics</span>
                    </span>
                    <button 
                      onClick={fetchHealthAndMetrics}
                      className="text-[10px] font-mono hover:text-red-400 flex items-center gap-1.5"
                    >
                      <RefreshCw className="w-3 h-3" />
                      <span>Poll Diagnostics</span>
                    </button>
                  </h3>

                  {health ? (
                    <div className="space-y-4 text-xs font-mono">
                      <div>
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">SQLite database</span>
                        <div className="flex items-center justify-between mt-1">
                          <span className="text-slate-300">{health.database.path}</span>
                          <span className="text-green-400 font-bold uppercase">{health.database.status}</span>
                        </div>
                        {health.database.errors.map((e, i) => (
                          <div key={i} className="text-red-400 mt-1 text-[11px] flex items-center gap-1">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            <span>{e}</span>
                          </div>
                        ))}
                      </div>

                      <div>
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Ollama API / Local LLM</span>
                        <div className="flex items-center justify-between mt-1">
                          <span className="text-slate-300">{health.ollama.model}</span>
                          <span className={`font-bold uppercase ${health.ollama.status === 'skipped' ? 'text-yellow-400' : 'text-green-400'}`}>
                            {health.ollama.status}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-600 block mt-0.5">{health.ollama.url}</span>
                      </div>

                      <div>
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Plugin API Bridge</span>
                        <div className="flex items-center justify-between mt-1">
                          <span className="text-slate-300">v{health.plugin.api_version}</span>
                          <span className="text-slate-300 font-bold">{health.plugin.capability_count} capabilities</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Checking local companion health...</p>
                  )}
                </div>

                {/* Local usage metrics */}
                <div className="bg-[#0c0e17] border border-[#1a1c29] rounded-xl p-6 shadow-md">
                  <h3 className="font-semibold text-sm border-b border-[#1d2030] pb-3.5 mb-4 flex items-center gap-2">
                    <Activity className="w-5 h-5 text-red-500" />
                    <span>Invocations & System Telemetry</span>
                  </h3>

                  {metrics ? (
                    <div className="space-y-4 text-xs font-mono">
                      <div>
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Active Tool usage</span>
                        <div className="grid grid-cols-2 gap-4 mt-2">
                          <div className="bg-slate-950/60 p-3 rounded border border-slate-900 text-center">
                            <div className="text-slate-500 text-[9px] uppercase">Invocations</div>
                            <div className="text-slate-200 font-bold text-lg mt-0.5">{metrics.tools.invocations}</div>
                          </div>
                          <div className="bg-slate-950/60 p-3 rounded border border-slate-900 text-center">
                            <div className="text-slate-500 text-[9px] uppercase">Failures</div>
                            <div className="text-red-400 font-bold text-lg mt-0.5">{metrics.tools.failures}</div>
                          </div>
                        </div>
                      </div>

                      <div>
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Observability Logs</span>
                        <div className="flex items-center justify-between mt-1 border-b border-slate-900 pb-1">
                          <span className="text-slate-400">Total metrics events logged</span>
                          <span className="text-slate-200">{metrics.events.total}</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Telemetry engine offline...</p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
