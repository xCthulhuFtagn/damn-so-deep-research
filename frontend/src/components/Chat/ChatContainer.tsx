import { useState, useRef, useEffect } from 'react';
import { Message } from '../../types';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import { Loader2, Pause, AlertCircle, Search } from 'lucide-react';

interface ChatContainerProps {
  messages: Message[];
  isRunning: boolean;
  phase: string;
  onSendMessage: (message: string) => void;
  onPause: () => void;
  searchThemes: string[];
  error: string | null;
  onClearError: () => void;
}

export default function ChatContainer({
  messages,
  isRunning,
  phase,
  onSendMessage,
  onPause,
  searchThemes,
  error,
  onClearError,
}: ChatContainerProps) {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!inputValue.trim()) return;
    onSendMessage(inputValue);
    setInputValue('');
  };

  const canSend = !isRunning || phase === 'paused' || phase === 'idle';

  return (
    <div className="flex-1 flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Research Chat</h2>
          {isRunning && (
            <div className="flex items-center gap-2 text-sm text-primary-600 dark:text-primary-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{phase}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isRunning && (
            <button
              onClick={onPause}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 rounded-md hover:bg-yellow-200 dark:hover:bg-yellow-900/50"
            >
              <Pause className="w-4 h-4" />
              Pause
            </button>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="px-6 py-3 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800 flex items-center justify-between">
          <div className="flex items-center gap-2 text-red-700 dark:text-red-300">
            <AlertCircle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
          <button
            onClick={onClearError}
            className="text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-200"
          >
            &times;
          </button>
        </div>
      )}

      {/* Parallel Search Indicator */}
      {searchThemes.length > 0 && (
        <div className="px-6 py-3 bg-primary-50 dark:bg-primary-900/10 border-b border-primary-200 dark:border-primary-800">
          <div className="flex items-center gap-2 text-primary-700 dark:text-primary-300">
            <Search className="w-4 h-4" />
            <span className="text-sm font-medium">
              Searching {searchThemes.length} themes in parallel:
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {searchThemes.map((theme, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-white dark:bg-slate-800 rounded text-xs text-primary-700 dark:text-primary-300 border border-primary-200 dark:border-primary-800"
              >
                {theme}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-500 dark:text-slate-400">
            <div className="text-center">
              <p className="text-lg">What would you like to research?</p>
              <p className="text-sm mt-2">
                Type your research query below to begin
              </p>
            </div>
          </div>
        ) : (
          <MessageList messages={messages} />
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <MessageInput
        value={inputValue}
        onChange={setInputValue}
        onSend={handleSend}
        disabled={!canSend}
        placeholder={
          isRunning
            ? 'Research in progress...'
            : messages.length === 0
              ? 'Enter your research query...'
              : 'Type a message or question...'
        }
      />
    </div>
  );
}
