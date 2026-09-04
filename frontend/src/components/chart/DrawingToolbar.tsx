import { useState } from 'react';
import { Pencil, Triangle, Square, ArrowRight, Minus, GitBranch, Trash2, Save } from 'lucide-react';

const TOOLS = [
    { key: 'trend', Icon: Pencil, label: 'Trend' },
    { key: 'fib', Icon: Triangle, label: 'Fib' },
    { key: 'rect', Icon: Square, label: 'Rect' },
    { key: 'arrow', Icon: ArrowRight, label: 'Arrow' },
    { key: 'hline', Icon: Minus, label: 'H-Line' },
    { key: 'fork', Icon: GitBranch, label: 'Fork' },
];

export default function DrawingToolbar() {
    const [selected, setSelected] = useState<string | null>(null);

    return (
        <div
            className="panel border-b flex items-center gap-2 px-4 py-1.5"
            style={{ borderBottomWidth: 1, borderBottomStyle: 'solid' }}
        >
            <span className="text-xs mr-1" style={{ color: 'var(--color-text-sub)' }}>Drawing:</span>
            {TOOLS.map(({ key, Icon, label }) => (
                <button
                    key={key}
                    onClick={() => setSelected(selected === key ? null : key)}
                    title={label}
                    className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg whitespace-nowrap transition-all cursor-pointer"
                    style={
                        selected === key
                            ? {
                                background: 'rgba(250,204,21,0.2)',
                                color: 'var(--color-yellow)',
                                border: '1px solid rgba(250,204,21,0.3)',
                            }
                            : { color: 'var(--color-text-sub)', border: '1px solid transparent' }
                    }
                    onMouseEnter={(e) => { if (selected !== key) e.currentTarget.style.background = 'var(--color-hover)'; }}
                    onMouseLeave={(e) => { if (selected !== key) e.currentTarget.style.background = 'transparent'; }}
                >
                    <Icon size={12} />
                    <span className="hidden sm:inline">{label}</span>
                </button>
            ))}
            <div className="ml-auto flex gap-2">
                <button
                    title="Clear drawings"
                    className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg whitespace-nowrap cursor-pointer"
                    style={{ color: 'var(--color-text-sub)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                    <Trash2 size={12} />
                    Clear
                </button>
                <button
                    title="Save drawings"
                    className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg whitespace-nowrap cursor-pointer"
                    style={{ color: 'var(--color-text-sub)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                    <Save size={12} />
                    Save
                </button>
            </div>
        </div>
    );
}
