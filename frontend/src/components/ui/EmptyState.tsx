import { ReactNode } from 'react';

interface EmptyStateProps {
    icon?: ReactNode;
    title: string;
    message: string;
    action?: {
        label: string;
        onClick: () => void;
    };
}

export function EmptyState({ icon, title, message, action }: EmptyStateProps) {
    return (
        <div
            className="panel border rounded-2xl p-8 text-center"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            {icon && <div className="mb-3 flex justify-center">{icon}</div>}
            <p className="text-sm font-medium mb-1">{title}</p>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>
                {message}
            </p>
            {action && (
                <button onClick={action.onClick} className="btn-accent">
                    {action.label}
                </button>
            )}
        </div>
    );
}
