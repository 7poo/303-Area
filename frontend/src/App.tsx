import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Bot, ChevronRight, CircleDollarSign, LoaderCircle, MessageSquare, PackageSearch, RefreshCw, Search, ShieldCheck, Sparkles, Store, TrendingUp } from 'lucide-react'
import { api, Alert, Peer, Product, Recommendation, Signal } from './api'

const money = (value?: number, currency = 'VND') => value == null ? '—' : new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(value) + ` ${currency}`
const pct = (value?: number) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
const label = (value?: string) => (value || '').replaceAll('_', ' ')
type Page = 'overview' | 'sku' | 'alerts' | 'recommendations'
const pageFromHash = (): Page => {
  const value = window.location.hash.replace('#', '')
  return value === 'sku' || value === 'alerts' || value === 'recommendations' ? value : 'overview'
}

function App() {
  const [country, setCountry] = useState('vn')
  const [products, setProducts] = useState<Product[]>([])
  const [totalProducts, setTotalProducts] = useState(0)
  const [globalAlerts, setGlobalAlerts] = useState<Alert[]>([])
  const [globalRecommendations, setGlobalRecommendations] = useState<Recommendation[]>([])
  const [selected, setSelected] = useState<Product | null>(null)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<{ product: Product; signal?: Signal; peers: Peer[]; alerts: Alert[]; recommendation?: Recommendation } | null>(null)
  const [chatOpen, setChatOpen] = useState(true)
  const [page, setPage] = useState<Page>(pageFromHash)
  const [approvalOpen, setApprovalOpen] = useState(false)

  const navigate = (next: Page) => {
    window.location.hash = next === 'overview' ? '' : next
    setPage(next)
  }

  const loadProducts = async () => {
    setLoading(true); setError('')
    try {
      const result = await api.products(country, undefined, search)
      setProducts(result.data || [])
      setTotalProducts(result.meta?.total_count ?? result.data?.length ?? 0)
      if (!selected || selected.country_code !== country || !result.data.some((item) => item.item_id === selected.item_id && item.shop_id === selected.shop_id)) setSelected(result.data[0] || null)
    } catch (err) { setError(err instanceof Error ? err.message : 'Không tải được dữ liệu') } finally { setLoading(false) }
  }
  useEffect(() => { void loadProducts() }, [country])
  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  useEffect(() => {
    let cancelled = false
    Promise.allSettled([api.alertsOverview(country), api.recommendationsOverview(country)]).then(([alerts, recommendations]) => {
      if (cancelled) return
      setGlobalAlerts(alerts.status === 'fulfilled' ? alerts.value.data || [] : [])
      setGlobalRecommendations(recommendations.status === 'fulfilled' ? recommendations.value.data || [] : [])
    })
    return () => { cancelled = true }
  }, [country])
  useEffect(() => {
    if (!selected) { setDetail(null); return }
    let cancelled = false
    setDetail(null)
    Promise.allSettled([api.product(country, selected.shop_id, selected.item_id), api.signals(country, selected.shop_id, selected.item_id), api.peers(country, selected.shop_id, selected.item_id), api.alerts(country, selected.shop_id, selected.item_id), api.recommendation(country, selected.shop_id, selected.item_id)])
      .then(([product, signal, peers, alerts, recommendation]) => {
        if (cancelled) return
        const value = <T,>(result: PromiseSettledResult<{ data: T }>) => result.status === 'fulfilled' ? result.value.data : undefined
        const productData = value(product)
        if (!productData) { setError('SKU không còn trong publication hiện tại'); return }
        setDetail({ product: productData, signal: value(signal), peers: value(peers) || [], alerts: value(alerts) || [], recommendation: value(recommendation) })
      })
    return () => { cancelled = true }
  }, [selected, country])

  const stats = useMemo(() => {
    const active = products.filter((p) => !p.is_sold_out).length
    const avgDiscount = products.length ? products.reduce((sum, p) => sum + (p.discount_percent || 0), 0) / products.length : 0
    return { active, avgDiscount }
  }, [products])

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>Market IQ</strong><span>Decision intelligence</span></div></div>
      <nav><button className={page === 'overview' ? 'active' : ''} onClick={() => navigate('overview')}><TrendingUp size={17} /> Market overview</button><button className={page === 'sku' ? 'active' : ''} onClick={() => navigate('sku')}><PackageSearch size={17} /> SKU 360</button><button className={page === 'alerts' ? 'active' : ''} onClick={() => navigate('alerts')}><AlertTriangle size={17} /> Competitor alerts <em>{globalAlerts.length}</em></button><button className={page === 'recommendations' ? 'active' : ''} onClick={() => navigate('recommendations')}><CircleDollarSign size={17} /> Recommendations <em>{globalRecommendations.length}</em></button></nav>
      <div className="sidebar-bottom"><div className="status-dot"><span /> Data pipeline healthy</div><small>Published snapshots<br />{detail?.signal?.snapshot_date || '—'}</small></div>
    </aside>
    <main className="main" onClick={(event) => { const target = event.target as HTMLElement; if (target.closest('.approve-button')) setApprovalOpen(true); if (target.closest('.product-row')) navigate('sku') }}>
      <header className="topbar"><div><p className="eyebrow">OPERATIONS CONSOLE / 05</p><h1>{page === 'overview' ? 'Market overview' : page === 'sku' ? 'SKU 360' : page === 'alerts' ? 'Competitor alerts' : 'Recommendations'}</h1></div><div className="top-actions"><select value={country} onChange={(e) => setCountry(e.target.value)}><option value="vn">🇻🇳 Vietnam</option><option value="id">🇮🇩 Indonesia</option></select><button className="icon-button" onClick={() => void loadProducts()} title="Refresh"><RefreshCw size={17} /></button><div className="avatar">MA</div></div></header>
      {error && <div className="error-banner"><AlertTriangle size={16} /> {error}<button onClick={() => setError('')}>×</button></div>}
      <section className="metric-grid"><Metric icon={<Store />} label="Tracked SKUs" value={loading ? '…' : totalProducts.toLocaleString('vi-VN')} hint={`${products.length} đang hiển thị`} /><Metric icon={<CircleDollarSign />} label="Avg. discount" value={`${stats.avgDiscount.toFixed(1)}%`} hint="trong snapshot hiện tại" /><Metric icon={<ShieldCheck />} label="Data confidence" value="High" hint="publication verified" good /><Metric icon={<AlertTriangle />} label="Open alerts" value={globalAlerts.length.toString()} hint="toàn bộ phạm vi đang chọn" /></section>
      {page === 'overview' && <div className="workspace"><section className="panel catalogue"><div className="panel-heading"><div><p className="eyebrow">CATALOGUE</p><h2>Products to watch</h2></div><div className="search"><Search size={16} /><input placeholder="Search product name" value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void loadProducts()} /></div></div>{loading ? <div className="loading"><LoaderCircle className="spin" /> Loading published products…</div> : <div className="product-list">{products.map((product) => <button key={`${product.shop_id}-${product.item_id}`} className={`product-row ${selected?.item_id === product.item_id && selected?.shop_id === product.shop_id ? 'selected' : ''}`} onClick={() => setSelected(product)}><div className="product-thumb">{product.image_url ? <img src={product.image_url} /> : <PackageSearch size={19} />}</div><div className="product-copy"><strong>{product.product_name || 'Unnamed product'}</strong><span>{product.brand || product.shop_name || '—'} · SKU {product.item_id}</span></div><div className="product-price"><strong>{money(product.price, product.currency)}</strong><span>{product.discount_percent ? `-${product.discount_percent.toFixed(0)}%` : 'No promo'}</span></div><ChevronRight size={16} className="chevron" /></button>)}{!products.length && !loading && <div className="empty">Không tìm thấy sản phẩm trong phạm vi này.</div>}</div>}</section>
        <section className="panel copilot"><div className="panel-heading"><div><p className="eyebrow">AI COPILOT</p><h2>Ask about your market</h2></div><div className="online"><span /> Online</div></div><div className="copilot-hero"><div className="bot-orb"><Bot size={25} /></div><p>Hỏi về giá, peer, cảnh báo hoặc chiến lược cho SKU đang chọn.</p></div><ChatPanel selected={selected} /> </section></div>}
      {page === 'overview' && detail && <Detail detail={detail} />}
      {page === 'sku' && (detail ? <Detail detail={detail} /> : <PageEmpty message="Chọn một sản phẩm ở Market overview để mở SKU 360." />)}
      {page === 'alerts' && <AlertCenterPage alerts={globalAlerts} onSelect={async (alert) => { let product = products.find((item) => item.item_id === alert.source_item_id && item.shop_id === alert.source_shop_id); if (!product && alert.source_item_id && alert.source_shop_id) { try { product = (await api.product(country, alert.source_shop_id, alert.source_item_id)).data } catch { setError('Không tải được SKU từ alert') } } if (product) { setSelected(product); navigate('sku') } }} />}
      {page === 'recommendations' && <RecommendationCenterPage recommendations={globalRecommendations} products={products} onReview={() => setApprovalOpen(true)} />}
      {page !== 'overview' && <section className="panel page-copilot"><div className="panel-heading"><div><p className="eyebrow">AI COPILOT</p><h2>Ask about this workspace</h2></div><div className="online"><span /> Online</div></div><ChatPanel selected={selected} /></section>}
      {approvalOpen && <ApprovalModal onClose={() => setApprovalOpen(false)} />}
    </main>
    {chatOpen && <button className="mobile-chat" onClick={() => setChatOpen(false)}><MessageSquare size={17} /> Copilot</button>}
  </div>
}

function Metric({ icon, label: title, value, hint, good }: { icon: React.ReactNode; label: string; value: string; hint: string; good?: boolean }) { return <div className="metric"><div className="metric-icon">{icon}</div><div><span>{title}</span><strong>{value}</strong><small className={good ? 'good' : ''}>{hint}</small></div></div> }

function PageEmpty({ message }: { message: string }) { return <section className="panel page-empty"><PackageSearch size={28} /><h2>Chưa có SKU được chọn</h2><p>{message}</p></section> }

function AlertPage({ alerts }: { alerts: Alert[] }) { return <section className="panel page-panel"><div className="panel-heading"><div><p className="eyebrow">ALERT CENTER</p><h2>Competitor alerts for selected SKU</h2></div><span className="count-pill alert-count">{alerts.length} alerts</span></div>{alerts.length ? alerts.map((alert, index) => <div className="alert-row alert-row-large" key={`${alert.alert_type}-${index}`}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={16} /></div><div><strong>{label(alert.alert_type)}</strong><span>{label(alert.metric_name)} · value {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} · threshold {alert.threshold ?? '—'}</span><small>{alert.snapshot_date} · evidence available</small></div><b className={`severity-text ${alert.severity}`}>{alert.severity}</b></div>) : <div className="empty">Không có alert hoặc chưa đủ evidence.</div>}</section> }

function RecommendationPage({ recommendation, product }: { recommendation: Recommendation; product: Product }) { return <section className="panel page-panel recommendation-page"><div className="panel-heading"><div><p className="eyebrow">DECISION SUPPORT</p><h2>Recommendation review</h2></div><span className={`badge ${recommendation.priority}`}>{recommendation.priority}</span></div><div className="recommendation recommendation-inline"><div className="recommendation-icon"><Sparkles size={19} /></div><div className="recommendation-body"><p className="eyebrow">SKU {product.item_id} / {recommendation.confidence} confidence</p><h3>{recommendation.action}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Current price<strong>{money(recommendation.source_price, product.currency)}</strong></span><span>Suggested price<strong>{money(recommendation.recommended_price, product.currency)}</strong></span><span>Constraint<strong>{label(recommendation.constraint_status)}</strong></span></div></div><button className="approve-button">Review action <ChevronRight size={16} /></button></div></section> }

function AlertCenterPage({ alerts, onSelect }: { alerts: Alert[]; onSelect: (alert: Alert) => void }) { return <section className="panel page-panel"><div className="panel-heading"><div><p className="eyebrow">ALERT CENTER</p><h2>All competitor alerts</h2></div><span className="count-pill alert-count">{alerts.length} alerts</span></div>{alerts.length ? alerts.map((alert, index) => <button className="alert-row alert-row-large alert-button" key={`${alert.alert_type}-${alert.source_item_id}-${index}`} onClick={() => onSelect(alert)}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={16} /></div><div><strong>{label(alert.alert_type)} · SKU {alert.source_item_id}</strong><span>{label(alert.metric_name)} · value {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} · threshold {alert.threshold ?? '—'}</span><small>{alert.snapshot_date} · click to open SKU 360</small></div><b className={`severity-text ${alert.severity}`}>{alert.severity}</b></button>) : <div className="empty">Không có alert hoặc chưa đủ evidence.</div>}</section> }

function RecommendationCenterPage({ recommendations, products, onReview }: { recommendations: Recommendation[]; products: Product[]; onReview: () => void }) { return <section className="panel page-panel"><div className="panel-heading"><div><p className="eyebrow">DECISION SUPPORT</p><h2>Recommendations to review</h2></div><span className="count-pill">{recommendations.length}</span></div>{recommendations.length ? recommendations.map((recommendation, index) => { const product = products.find((item) => item.item_id === recommendation.source_item_id && item.shop_id === recommendation.source_shop_id); return <div className="recommendation recommendation-list-item" key={`${recommendation.source_item_id}-${index}`}><div className="recommendation-icon"><Sparkles size={18} /></div><div className="recommendation-body"><p className="eyebrow">SKU {recommendation.source_item_id} · {recommendation.priority} priority</p><h3>{recommendation.action}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Current<strong>{money(recommendation.source_price, product?.currency || recommendation.currency)}</strong></span><span>Suggested<strong>{money(recommendation.recommended_price, product?.currency || recommendation.currency)}</strong></span><span>Confidence<strong>{recommendation.confidence}</strong></span></div></div><button className="approve-button" onClick={onReview}>Review action <ChevronRight size={16} /></button></div> }) : <div className="empty">Không có recommendation cần review.</div>}</section> }

function ApprovalModal({ onClose }: { onClose: () => void }) { const [reason, setReason] = useState(''); const [submitted, setSubmitted] = useState(false); return <div className="modal-backdrop" role="presentation" onClick={onClose}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="approval-title" onClick={(event) => event.stopPropagation()}><div className="modal-header"><div><p className="eyebrow">REVIEW WORKFLOW</p><h2 id="approval-title">Review recommended action</h2></div><button className="modal-close" onClick={onClose}>×</button></div>{submitted ? <div className="modal-success"><ShieldCheck size={23} /><h3>Review recorded locally</h3><p>Đây là bản MVP preview. Chưa có connector thay đổi giá thật.</p><button className="approve-button" onClick={onClose}>Đóng</button></div> : <><p className="modal-copy">Kiểm tra evidence và ghi lý do trước khi đưa action vào kế hoạch xử lý.</p><textarea placeholder="Reason / note (optional)" value={reason} onChange={(event) => setReason(event.target.value)} /><div className="modal-actions"><button className="secondary-button" onClick={onClose}>Cancel</button><button className="approve-button" onClick={() => setSubmitted(true)}>Create action plan <ChevronRight size={16} /></button></div></>}</div></div> }

function Detail({ detail }: { detail: { product: Product; signal?: Signal; peers: Peer[]; alerts: Alert[]; recommendation?: Recommendation } }) {
  const { product, signal, peers, alerts, recommendation } = detail
  const pressure = String(signal?.competitive_pressure_level || 'low')
  return <section className="detail"><div className="detail-header"><div><p className="eyebrow">SKU 360 / {product.item_id}</p><h2>{product.product_name}</h2><span className="muted">{product.shop_name} · {product.brand || 'Unbranded'} · snapshot {product.snapshot_date}</span></div><a className="outline-button" href={product.url} target="_blank" rel="noreferrer">Open listing <ArrowUpRight size={15} /></a></div><div className="detail-grid"><div className="panel sku-card"><div className="sku-card-top"><div className="large-thumb">{product.image_url ? <img src={product.image_url} /> : <PackageSearch />}</div><div><span className="eyebrow">CURRENT OFFER</span><h3>{money(product.price, product.currency)}</h3><p>{product.discount_percent ? `${product.discount_percent.toFixed(0)}% promotion` : 'No promotion'} · {product.rating?.toFixed(1) || '—'} rating</p></div></div><div className="price-bars"><Bar label="Your price" value={product.price} max={Math.max(product.price || 1, Number(signal?.peer_median_price) || 1)} color="blue" /><Bar label="Peer median" value={Number(signal?.peer_median_price)} max={Math.max(product.price || 1, Number(signal?.peer_median_price) || 1)} color="orange" /></div></div><div className="panel signal-card"><div className="panel-heading compact"><div><p className="eyebrow">MARKET SIGNAL</p><h3>Competitive pressure</h3></div><span className={`badge ${pressure}`}>{pressure}</span></div><div className="signal-value">{signal?.competitive_pressure_score == null ? '—' : `${(Number(signal.competitive_pressure_score) * 100).toFixed(0)} / 100`}<small>{signal?.signal_confidence || 'low'} confidence · {signal?.peer_count || 0} peers</small></div><div className="signal-row"><span>Price gap vs peers</span><strong>{pct(Number(signal?.price_gap_pct))}</strong></div><div className="signal-row"><span>Peer sales momentum</span><strong>{pct(Number(signal?.peer_sales_momentum_pct))}</strong></div></div></div><div className="detail-grid lower"><section className="panel"><div className="panel-heading compact"><div><p className="eyebrow">MATCHED PEERS</p><h3>Competitor set</h3></div><span className="count-pill">{peers.length}</span></div>{peers.length ? peers.map((peer) => <div className="peer-row" key={`${peer.target_shop_id}-${peer.target_item_id}`}><div><strong>{peer.product_name || `SKU ${peer.target_item_id}`}</strong><span>{peer.brand || '—'} · {peer.relation} · {peer.confidence}</span></div><strong>{money(peer.price, peer.currency)}</strong><span className="match-score">{(peer.match_score * 100).toFixed(0)}%</span></div>) : <div className="empty">Not enough evidence to identify peers.</div>}</section><section className="panel"><div className="panel-heading compact"><div><p className="eyebrow">COMPETITOR ALERTS</p><h3>What changed</h3></div><span className="count-pill alert-count">{alerts.length}</span></div>{alerts.length ? alerts.slice(0, 4).map((alert, i) => <div className="alert-row" key={`${alert.alert_type}-${i}`}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={15} /></div><div><strong>{label(alert.alert_type)}</strong><span>{label(alert.metric_name)} · {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} (threshold {alert.threshold ?? '—'})</span></div><small>{alert.severity}</small></div>) : <div className="empty">No open competitor alert.</div>}</section></div>{recommendation && <section className="recommendation"><div className="recommendation-icon"><Sparkles size={19} /></div><div className="recommendation-body"><p className="eyebrow">RECOMMENDATION / {recommendation.priority}</p><h3>{recommendation.action}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Confidence <strong>{recommendation.confidence}</strong></span><span>Suggested price <strong>{money(recommendation.recommended_price, product.currency)}</strong></span><span>Guardrail <strong>{label(recommendation.constraint_status)}</strong></span></div></div><button className="approve-button">Review action <ChevronRight size={16} /></button></section>}</section>
}

function Bar({ label: title, value, max, color }: { label: string; value?: number; max: number; color: string }) { return <div className="bar-row"><span>{title}</span><div className="bar-track"><i className={color} style={{ width: `${Math.min(100, ((value || 0) / max) * 100)}%` }} /></div><strong>{value == null ? '—' : value.toLocaleString('vi-VN')}</strong></div> }

function ChatPanel({ selected }: { selected: Product | null }) {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const ask = async (text = message) => { if (!text.trim()) return; setBusy(true); setReply(''); try { const result = await api.chat(text, selected || {}); setReply(String(result.answer || 'Không có câu trả lời.')) } catch (err) { setReply(err instanceof Error ? err.message : 'Copilot không phản hồi') } finally { setBusy(false); setMessage('') } }
  return <div className="chat"><div className="suggestions"><button onClick={() => void ask('Tóm tắt thị trường cho SKU đang chọn')}>Summarize this SKU</button><button onClick={() => void ask('Đối thủ nào đang gây áp lực?')}>Find pressure</button><button onClick={() => void ask('Đề xuất giá và khuyến mãi')}>Recommend action</button></div>{reply && <div className="chat-reply"><Bot size={16} /><p>{reply}</p></div>}<div className="chat-input"><input placeholder="Ask a question…" value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void ask()} /><button onClick={() => void ask()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUpRight size={17} />}</button></div><small className="privacy"><ShieldCheck size={12} /> Read-only insights · không thay đổi listing</small></div>
}

export default App
