"use client";

import { createContext, useCallback, useContext, useState } from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";
import { cn } from "../../lib/cn";

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: "success" | "critical" | "info";
}

const ToastContext = createContext<((toast: Omit<ToastItem, "id">) => void) | null>(null);

export function useToast() {
  const fn = useContext(ToastContext);
  if (!fn) throw new Error("useToast must be used within <ToastProvider>");
  return fn;
}

const ICONS = { success: CheckCircle2, critical: AlertCircle, info: Info };
const TONE_CLASSES = {
  success: "text-success-fg",
  critical: "text-critical-fg",
  info: "text-info-fg",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const push = useCallback((toast: Omit<ToastItem, "id">) => {
    setToasts((prev) => [...prev, { ...toast, id: Date.now() + Math.random() }]);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        {toasts.map((toast) => {
          const Icon = ICONS[toast.tone];
          return (
            <ToastPrimitive.Root
              key={toast.id}
              duration={5000}
              onOpenChange={(open) => {
                if (!open) setToasts((prev) => prev.filter((t) => t.id !== toast.id));
              }}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-border bg-bg-raised p-4 shadow-[var(--shadow-popover)]",
                "motion-safe:data-[state=open]:[animation:toast-in_180ms_ease-out]",
              )}
            >
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", TONE_CLASSES[toast.tone])} aria-hidden="true" />
              <div className="flex-1 space-y-0.5">
                <ToastPrimitive.Title className="text-sm font-medium text-fg">{toast.title}</ToastPrimitive.Title>
                {toast.description && (
                  <ToastPrimitive.Description className="text-xs text-fg-muted">
                    {toast.description}
                  </ToastPrimitive.Description>
                )}
              </div>
              <ToastPrimitive.Close className="rounded p-1 text-fg-subtle hover:bg-surface-hover">
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="sr-only">Dismiss</span>
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          );
        })}
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
