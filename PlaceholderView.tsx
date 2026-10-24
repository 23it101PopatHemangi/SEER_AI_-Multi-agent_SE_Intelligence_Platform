import React from 'react';
import { Construction } from 'lucide-react';

interface PlaceholderViewProps {
  title: string;
  description: string;
}

export const PlaceholderView: React.FC<PlaceholderViewProps> = ({ title, description }) => {
  return (
    <div className="flex-1 flex flex-col justify-center items-center p-8 text-center min-h-[500px]">
      <div className="inline-flex items-center justify-center p-4 bg-primary-500/10 rounded-2xl border border-primary-500/20 text-primary-500 dark:text-primary-400 mb-6">
        <Construction className="w-10 h-10" />
      </div>
      <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">{title}</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md">{description}</p>
      <div className="mt-8 flex space-x-3">
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
          Step 2 Placeholder
        </span>
      </div>
    </div>
  );
};
