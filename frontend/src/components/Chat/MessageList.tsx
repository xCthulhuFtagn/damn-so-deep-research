import { Message } from '../../types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clsx } from 'clsx';
import { User, Bot, Wrench } from 'lucide-react';

interface MessageListProps {
  messages: Message[];
}

function getMessageIcon(role: Message['role']) {
  switch (role) {
    case 'user':
      return <User className="w-5 h-5" />;
    case 'assistant':
      return <Bot className="w-5 h-5" />;
    case 'tool':
      return <Wrench className="w-5 h-5" />;
    default:
      return <Bot className="w-5 h-5" />;
  }
}

function getMessageStyle(role: Message['role']) {
  switch (role) {
    case 'user':
      return 'bg-primary-50 dark:bg-primary-900/20 border-primary-200 dark:border-primary-800';
    case 'assistant':
      return 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700';
    case 'tool':
      return 'bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700';
    default:
      return 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700';
  }
}

export default function MessageList({ messages }: MessageListProps) {
  return (
    <div className="space-y-4">
      {messages.map((message, index) => (
        <div
          key={index}
          className={clsx(
            'rounded-lg border p-4',
            getMessageStyle(message.role)
          )}
        >
          <div className="flex items-start gap-3">
            <div
              className={clsx(
                'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
                message.role === 'user'
                  ? 'bg-primary-100 dark:bg-primary-900 text-primary-600 dark:text-primary-300'
                  : message.role === 'tool'
                  ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
              )}
            >
              {getMessageIcon(message.role)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  {message.name ||
                    (message.role === 'user'
                      ? 'You'
                      : message.role === 'tool'
                      ? 'Tool'
                      : 'Assistant')}
                </span>
                <span className="text-xs text-slate-400 dark:text-slate-500">
                  {message.role}
                </span>
              </div>
              <div className="prose prose-sm prose-slate dark:prose-invert max-w-none markdown-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
