import { useState, useEffect, useCallback } from 'react';
import { Bell, BellPlus, X } from 'lucide-react';
import alertService from '@/services/alertService';
import useAuthStore from '@/store/authStore';

const ALERT_TYPES = ['Price Above', 'Price Below', 'RSI Below', 'RSI Above', 'Golden Cross', 'Death Cross', 'Volume Spike'];

const STATUS_STYLE = {
    active: { dot: 'var(--color-green)', label: '● Active', color: 'var(--color-green)' },
    triggered: { dot: 'var(--color-yellow)', label: '✅ Triggered', color: 'var(--color-yellow)' },
    inactive: { dot: 'var(--color-text-sub)', label: '○ Inactive', color: 'var(--color-text-sub)' },
};

const EMPTY_FORM = { symbol: '', alert_type: 'Price Above', condition: 'above', value: '', channel: 'in_app' };

export default function AlertsPage() {
    const { isAuthenticated } = useAuthStore();
    const [alerts, setAlerts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [timedOut, setTimedOut] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);

    const loadAlerts = useCallback(async () => {
        if (!isAuthenticated) return;
        setLoading(true);
        setTimedOut(false);
        try {
            const res = await alertService.getAll();
            setAlerts(res.data);
        } catch (err: any) {
            if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
                setTimedOut(true);
            }
            // not authenticated or network error
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    useEffect(() => { loadAlerts(); }, [loadAlerts]);

    const handleCreate = async () => {
        if (!form.symbol || !form.value) return;
        setSaving(true);
        try {
            await alertService.create({
                symbol: form.symbol.toUpperCase(),
                alert_type: form.alert_type,
                condition: form.condition,
                value: parseFloat(form.value),
                channel: form.channel,
            });
            setShowModal(false);
            setForm(EMPTY_FORM);
            loadAlerts();
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id) => {
        try {
            await alertService.delete(id);
            setAlerts((prev) => prev.filter((a) => a.id !== id));
        } catch { /* ignore */ }
    };

    const handleToggle = async (id) => {
        try {
            const res = await alertService.toggle(id);
            setAlerts((prev) => prev.map((a) => a.id === id ? res.data : a));
        } catch { /* ignore */ }
    };

    const formField = (label, key, type = 'text', placeholder = '') => (
        <div>
            <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>{label}</div>
            <input
                type={type}
                className="input-field"
                placeholder={placeholder}
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
            />
        </div>
    );

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-3xl mx-auto animate-fade-in">

                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-base font-bold flex items-center gap-2"><Bell size={16} /> Price Alerts</h2>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>รับแจ้งเตือนเมื่อราคาถึงเป้าหมาย</p>
                    </div>
                    {isAuthenticated && (
                        <button onClick={() => setShowModal(true)} className="btn-accent flex items-center gap-1.5"><BellPlus size={12} /> สร้าง Alert</button>
                    )}
                </div>

                {!isAuthenticated ? (
                    <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex justify-center"><Bell size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                        <p className="text-sm font-medium mb-1">กรุณาเข้าสู่ระบบ</p>
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>ต้อง Login เพื่อสร้างและจัดการ alerts</p>
                    </div>
                ) : loading ? (
                    <div className="flex flex-col gap-3">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="panel border rounded-2xl px-4 py-3 h-14 animate-pulse" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }} />
                        ))}
                    </div>
                ) : timedOut ? (
                    <div className="panel border rounded-2xl p-8 text-center animate-fade-in" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="text-3xl mb-3">⏱</div>
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={loadAlerts} className="btn-accent">Retry</button>
                    </div>
                ) : alerts.length === 0 ? (
                    <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex justify-center"><Bell size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                        <p className="text-sm font-medium mb-1">ยังไม่มี alert</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>กดปุ่ม "สร้าง Alert" เพื่อตั้งการแจ้งเตือน</p>
                        <button onClick={() => setShowModal(true)} className="btn-accent flex items-center gap-1.5"><BellPlus size={12} /> สร้าง Alert</button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        {alerts.map((a) => {
                            const statusKey = a.status === 'TRIGGERED' ? 'triggered' : a.is_active ? 'active' : 'inactive';
                            const s = STATUS_STYLE[statusKey] || STATUS_STYLE.active;
                            return (
                                <div key={a.id} className="panel border rounded-2xl px-4 py-3 flex items-center gap-4" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                    <button onClick={() => handleToggle(a.id)} className="flex-shrink-0">
                                        <div className={`w-2 h-2 rounded-full ${a.is_active ? 'animate-pulse-dot' : ''}`} style={{ background: s.dot }} />
                                    </button>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-bold" style={{ color: 'var(--color-accent)' }}>{a.symbol}</span>
                                            <span className="badge badge-violet">{a.alert_type}</span>
                                        </div>
                                        <div className="text-[11px] mt-0.5 truncate" style={{ color: 'var(--color-text-sub)' }}>
                                            เงื่อนไข: {a.condition} {a.value} · via {a.channel}
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-[11px] mb-0.5" style={{ color: s.color }}>{s.label}</div>
                                    </div>
                                    <button onClick={() => handleDelete(a.id)} className="text-xs px-2 py-1 rounded-lg transition-colors" style={{ color: 'var(--color-text-sub)' }}
                                        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                                        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}><X size={12} /></button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Create Alert Modal */}
            {showModal && (
                <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
                    <div className="glass-panel rounded-2xl p-6 w-96 animate-slide-up">
                        <div className="flex items-center justify-between mb-5">
                            <h3 className="font-bold">สร้าง Alert ใหม่</h3>
                            <button onClick={() => setShowModal(false)} style={{ color: 'var(--color-text-sub)' }}><X size={14} /></button>
                        </div>
                        <div className="flex flex-col gap-3">
                            {formField('Symbol', 'symbol', 'text', 'เช่น PTT.BK, AAPL')}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ประเภท Alert</div>
                                <select className="input-field glass-select" value={form.alert_type} onChange={(e) => setForm((f) => ({ ...f, alert_type: e.target.value, condition: e.target.value.includes('Above') ? 'above' : 'below' }))}>
                                    {ALERT_TYPES.map((t) => <option key={t}>{t}</option>)}
                                </select>
                            </div>
                            {formField('ค่าเงื่อนไข', 'value', 'number', 'เช่น 40.00 หรือ 30 (RSI)')}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ช่องทางแจ้งเตือน</div>
                                <select className="input-field glass-select" value={form.channel} onChange={(e) => setForm((f) => ({ ...f, channel: e.target.value }))}>
                                    <option value="in_app">In-App</option>
                                    <option value="telegram">Telegram</option>
                                </select>
                            </div>
                            <div className="flex gap-2 mt-2">
                                <button onClick={() => setShowModal(false)} className="btn-outline flex-1 py-2">ยกเลิก</button>
                                <button onClick={handleCreate} disabled={saving} className="btn-accent flex-1 py-2">{saving ? 'กำลังบันทึก…' : 'สร้าง Alert'}</button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
