import React, { useState, useEffect, useRef } from 'react';
import { useOktaAuth } from '@okta/okta-react';
import { Navigate, useLocation } from 'react-router-dom';
import { Eye, ArrowRight, AlertCircle, Terminal } from 'lucide-react';

export const Login: React.FC = () => {
  const { authState, oktaAuth } = useOktaAuth();
  const location = useLocation();
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  // If already authenticated, redirect to projects/dashboard
  if (authState?.isAuthenticated) {
    const from = (location.state as any)?.from?.pathname || "/projects";
    return <Navigate to={from} replace />;
  }

  const handleLogin = async () => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const fromState = (location.state as any)?.from;
      const originalUri = fromState 
        ? fromState.pathname + fromState.search + fromState.hash 
        : '/projects';
        
      await oktaAuth.signInWithRedirect({ originalUri });
    } catch (err: any) {
      console.error('Okta sign in error:', err);
      setError(err.message || 'An error occurred during Okta authentication.');
      setIsLoggingIn(false);
    }
  };

  // Canvas Telemetry Animation Engine
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Core SEER AI stages mapping nodes
    const nodeLabels = ['GitHub', 'Architecture', 'Jira', 'Analytics', 'Risk', 'AI Insights'];
    const nodes: {
      x: number;
      y: number;
      baseX: number;
      baseY: number;
      vx: number;
      vy: number;
      radius: number;
      label: string;
      pulse: number;
    }[] = [];

    const numNodes = prefersReducedMotion ? 4 : (window.innerWidth < 768 ? 8 : 22);

    // Spacing configuration for key nodes on the left side
    for (let i = 0; i < 6; i++) {
      const angle = (i / 6) * Math.PI * 2;
      const x = width * 0.22 + Math.cos(angle) * (width * 0.12);
      const y = height * 0.5 + Math.sin(angle) * (height * 0.2);
      nodes.push({
        x,
        y,
        baseX: x,
        baseY: y,
        vx: 0,
        vy: 0,
        radius: 6,
        label: nodeLabels[i],
        pulse: Math.random() * Math.PI
      });
    }

    // Ambient floating network background nodes
    if (!prefersReducedMotion) {
      for (let i = 6; i < numNodes; i++) {
        const x = Math.random() * width;
        const y = Math.random() * height;
        nodes.push({
          x,
          y,
          baseX: x,
          baseY: y,
          vx: (Math.random() - 0.5) * 0.1,
          vy: (Math.random() - 0.5) * 0.1,
          radius: 2,
          label: '',
          pulse: 0
        });
      }
    }

    // Interactive moving data packets travelling between nodes
    const packets: {
      fromIndex: number;
      toIndex: number;
      progress: number;
      speed: number;
      color: string;
    }[] = [];

    const getConnections = (nodeIndex: number) => {
      const connections: number[] = [];
      const node = nodes[nodeIndex];
      const maxDistance = width * 0.26;
      
      nodes.forEach((otherNode, idx) => {
        if (idx === nodeIndex) return;
        const dx = node.x - otherNode.x;
        const dy = node.y - otherNode.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < maxDistance) {
          connections.push(idx);
        }
      });
      return connections;
    };

    const spawnPacket = () => {
      if (prefersReducedMotion || packets.length > 12) return;
      const fromIndex = Math.floor(Math.random() * nodes.length);
      const connections = getConnections(fromIndex);
      if (connections.length > 0) {
        const toIndex = connections[Math.floor(Math.random() * connections.length)];
        packets.push({
          fromIndex,
          toIndex,
          progress: 0,
          speed: 0.002 + Math.random() * 0.003,
          color: Math.random() > 0.4 ? '#8B5CF6' : '#6366F1'
        });
      }
    };

    // Pre-spawn packets
    for (let i = 0; i < (prefersReducedMotion ? 0 : 6); i++) {
      spawnPacket();
    }

    // Canvas Frame Drawer
    const draw = () => {
      ctx.fillStyle = '#06080D';
      ctx.fillRect(0, 0, width, height);

      // 1. Slow gradient light sweeps in background
      if (!prefersReducedMotion) {
        const time = Date.now() * 0.0003;
        const glowX = width * 0.3 + Math.sin(time) * (width * 0.1);
        const glowY = height * 0.5 + Math.cos(time * 0.7) * (height * 0.1);
        
        const grad = ctx.createRadialGradient(glowX, glowY, 50, glowX, glowY, width * 0.35);
        grad.addColorStop(0, 'rgba(139, 92, 246, 0.08)');
        grad.addColorStop(0.5, 'rgba(99, 102, 241, 0.03)');
        grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, width, height);
      }

      // 2. Draw static grid overlay
      ctx.strokeStyle = 'rgba(30, 41, 59, 0.15)';
      ctx.lineWidth = 0.5;
      const gridSize = 64;
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // 3. Draw connection lines
      const maxDistance = width * 0.26;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < maxDistance) {
            const alpha = (1 - dist / maxDistance) * 0.12;
            ctx.strokeStyle = `rgba(99, 102, 241, ${alpha})`;
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      // 4. Draw traveling data packets
      for (let i = packets.length - 1; i >= 0; i--) {
        const p = packets[i];
        p.progress += p.speed;
        
        if (p.progress >= 1) {
          packets.splice(i, 1);
          if (Math.random() > 0.3) spawnPacket();
          continue;
        }

        const from = nodes[p.fromIndex];
        const to = nodes[p.toIndex];
        const px = from.x + (to.x - from.x) * p.progress;
        const py = from.y + (to.y - from.y) * p.progress;

        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(px, py, 1.8, 0, Math.PI * 2);
        ctx.fill();
      }

      // 5. Draw active nodes and text labels
      nodes.forEach((n) => {
        if (!prefersReducedMotion) {
          n.pulse += 0.01;
          n.x = n.baseX + Math.sin(n.pulse * 0.8) * 3;
          n.y = n.baseY + Math.cos(n.pulse * 0.6) * 3;
        }

        if (n.label) {
          // Pulsing halo outer ring
          const ringRadius = n.radius + 6 + Math.sin(n.pulse * 2.5) * 2;
          ctx.strokeStyle = 'rgba(139, 92, 246, 0.22)';
          ctx.lineWidth = 0.75;
          ctx.beginPath();
          ctx.arc(n.x, n.y, ringRadius, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Solid inner node core
        ctx.fillStyle = n.label ? '#8B5CF6' : '#334155';
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fill();

        // Node labels
        if (n.label && width > 1024) {
          ctx.fillStyle = '#94A3B8';
          ctx.font = '10px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y - 12);
        }
      });

      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  return (
    <div className="min-h-screen w-full flex flex-col lg:flex-row bg-[#06080D] text-white overflow-hidden relative transition-colors duration-150">
      
      {/* Interactive Canvas Background Animation */}
      <canvas ref={canvasRef} className="absolute inset-0 z-0 pointer-events-none" />

      {/* LEFT PANEL: Branding Info */}
      <div className="relative w-full lg:w-[40%] flex flex-col justify-between p-8 md:p-12 lg:p-16 z-10 shrink-0 border-b lg:border-b-0 lg:border-r border-slate-900/60 bg-[#06080D]/40 backdrop-blur-[1px]">
        
        {/* Top Logo */}
        <div className="flex items-center space-x-2">
          <div className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white border border-white/15">
            <Eye className="w-5 h-5 text-primary-400" />
          </div>
          <span className="font-extrabold text-sm tracking-wider uppercase text-slate-100">
            SEER AI
          </span>
        </div>

        {/* Text descriptions */}
        <div className="space-y-5 my-12 lg:my-auto max-w-sm">
          <div className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-primary-500/10 text-primary-400 border border-primary-500/20 w-fit">
            <span>Engineering Workspace</span>
          </div>
          
          <h2 className="text-3xl lg:text-4xl font-extrabold tracking-tight leading-tight text-white">
            Software Engineering Intelligence
          </h2>
          <p className="text-sm text-slate-350 leading-relaxed">
            Understand your repositories, architecture, backlog and engineering risks in one place.
          </p>
        </div>

        {/* Footer */}
        <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest hidden lg:block">
          Enterprise Security Active
        </div>

      </div>

      {/* RIGHT PANEL: Centered premium authentication card */}
      <div className="flex-1 flex items-center justify-center p-6 md:p-12 lg:p-16 z-10 bg-[#06080D]/20">
        
        {/* Premium Glassmorphic Card (adds subtle shadow/glow boundary) */}
        <div className="w-full max-w-md bg-[#0d121f]/75 dark:bg-[#0d121f]/75 backdrop-blur-2xl border border-slate-800/80 text-white rounded-2xl p-8 shadow-[0_0_50px_rgba(99,102,241,0.15)] space-y-8 transition duration-150">
          
          {/* Header */}
          <div className="space-y-2 text-center md:text-left">
            <h3 className="text-xl font-extrabold tracking-tight text-white">
              Welcome to SEER AI
            </h3>
            <p className="text-sm text-slate-400">
              Sign in to your engineering workspace.
            </p>
          </div>

          {/* mobile screen indicators */}
          <div className="lg:hidden flex items-center space-x-2 p-3.5 bg-slate-900/60 rounded-xl border border-slate-800/40 text-[10px] text-slate-450">
            <Terminal className="w-4 h-4 text-primary-400 shrink-0" />
            <span>Telemetry pipelines: GitHub &bull; Architecture &bull; Jira</span>
          </div>

          {/* Errors widget */}
          {error && (
            <div className="flex items-start space-x-2 bg-red-950/20 border border-red-800/40 p-3 rounded-lg text-xs text-red-400">
              <AlertCircle className="w-4 h-4 shrink-0 text-red-500 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Okta Login Button */}
          <div className="space-y-4">
            <button
              onClick={handleLogin}
              disabled={isLoggingIn || !authState}
              className={`w-full py-3.5 px-4 rounded-xl font-bold flex items-center justify-center space-x-2 transition duration-200 border border-primary-500/20 shadow-[0_0_15px_rgba(139,92,246,0.15)] hover:shadow-[0_0_25px_rgba(139,92,246,0.35)] ${
                isLoggingIn || !authState
                  ? 'bg-slate-850 text-slate-500 cursor-not-allowed border-transparent shadow-none'
                  : 'bg-primary-600 hover:bg-primary-500 text-white active:bg-primary-700'
              }`}
            >
              {isLoggingIn ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Connecting to Okta...</span>
                </>
              ) : (
                <>
                  <span>Sign in with Okta</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>

            {!authState && (
              <p className="text-center text-[10px] text-slate-550 animate-pulse">
                Initializing Okta security layer...
              </p>
            )}
          </div>

          {/* Safety footnote */}
          <div className="pt-2 text-center text-[10px] text-slate-500 border-t border-slate-800/40">
            Secured by Okta Identity Cloud &bull; HTTPS encryption active
          </div>

        </div>

      </div>

    </div>
  );
};
export default Login;
