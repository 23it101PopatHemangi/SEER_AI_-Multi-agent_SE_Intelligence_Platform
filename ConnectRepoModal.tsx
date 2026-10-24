import React, { useState, useEffect } from 'react';
import { X, Github, AlertCircle } from 'lucide-react';
import { useOktaAuth } from '@okta/okta-react';
import { repositoryService, Repository } from '../services/repositoryService';

interface ConnectRepoModalProps {
  isOpen: boolean;
  projectId: string;
  onClose: () => void;
  onRepoConnected: (repository: Repository) => void | Promise<void>;
}

export const ConnectRepoModal: React.FC<ConnectRepoModalProps> = ({
  isOpen,
  projectId,
  onClose,
  onRepoConnected,
}) => {
  const { authState, oktaAuth } = useOktaAuth();
  const [url, setUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [userEmail, setUserEmail] = useState<string>('');

  // Fetch logged in user email for token scoping
  useEffect(() => {
    let active = true;
    if (authState?.isAuthenticated) {
      oktaAuth.getUser().then((user) => {
        if (active && user.email) {
          setUserEmail(user.email);
        }
      }).catch(err => console.error('Error fetching user email in connect modal', err));
    }
    return () => {
      active = false;
    };
  }, [authState, oktaAuth]);

  if (!isOpen) return null;

  const validateUrl = (inputUrl: string) => {
    // Basic regex validation for a GitHub repository URL
    const regex = /^https:\/\/github\.com\/[^/]+\/[^/]+$/;
    return regex.test(inputUrl.trim());
  };

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setError('GitHub repository URL is required.');
      return;
    }

    if (!validateUrl(trimmedUrl)) {
      setError(
        'Invalid URL. Please enter a valid public GitHub URL. Example: https://github.com/facebook/react'
      );
      return;
    }

    setIsLoading(true);
    
    try {
      // Simulate progressive status transitions as requested by requirements
      setStatusText('Connecting repository...');
      await sleep(1000);
      
      setStatusText('Fetching repository information...');
      await sleep(1000);
      
      setStatusText('Loading repository structure...');
      // Execute live connection to backend/GitHub
      await repositoryService.connectRepository(projectId, trimmedUrl, userEmail);
        const repository = await repositoryService.connectRepository(projectId, trimmedUrl, userEmail);
      
      // Success! Close modal and refresh repo listings
      onClose();
      onRepoConnected();
      await onRepoConnected(repository);
    } catch (err: any) {
      setError(err.message || 'Failed to connect repository. Make sure the repository is public.');
      setIsLoading(false);
    } finally {
      setStatusText('');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xl overflow-hidden transition-colors duration-150">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Github className="w-5 h-5 text-slate-800 dark:text-slate-200" />
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">Connect GitHub Repository</h3>
          </div>
          <button
            onClick={onClose}
            disabled={isLoading}
            className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Loading State Overlay */}
        {isLoading ? (
          <div className="p-12 flex flex-col items-center justify-center space-y-4">
            <div className="w-10 h-10 border-4 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 animate-pulse">
              {statusText}
            </p>
          </div>
        ) : (
          /* Form Body */
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {error && (
              <div className="flex items-start space-x-2 p-3 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/50 rounded-lg">
                <AlertCircle className="w-4 h-4 shrink-0 text-red-500 dark:text-red-400 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label
                htmlFor="repoUrl"
                className="text-sm font-semibold text-slate-700 dark:text-slate-300"
              >
                Public GitHub Repository URL
              </label>
              <input
                type="text"
                id="repoUrl"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/owner/repository"
                required
                className="w-full px-3 py-2 text-sm bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800 text-slate-900 dark:text-slate-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition"
              />
              <p className="text-[10px] text-slate-400 dark:text-slate-500">
                Only public repositories are supported in this release. e.g. https://github.com/facebook/react
              </p>
            </div>

            {/* Footer Buttons */}
            <div className="flex items-center justify-end space-x-3 pt-4 border-t border-slate-200 dark:border-slate-800">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 text-sm font-semibold text-white bg-primary-600 hover:bg-primary-500 rounded-lg shadow-sm transition"
              >
                Connect
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
export default ConnectRepoModal;
