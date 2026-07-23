import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Bot, ChevronRight, CircleDollarSign, LoaderCircle, MessageSquare, PackageSearch, RefreshCw, Search, ShieldCheck, Sparkles, Store, TrendingUp } from 'lucide-react'
import { api, Alert, Company, Peer, Product, Recommendation, Signal } from './api'

const money = (value?: number, currency = 'VND') => value == null || !Number.isFinite(Number(value)) ? '—' : new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(Number(value)) + ` ${currency}`
const pct = (value?: number) => value == null || !Number.isFinite(Number(value)) ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(1)}%`
const translations: Record<string, string> = {
  hold_price: 'Giữ nguyên giá', reduce_price: 'Điều chỉnh giảm giá', use_voucher: 'Dùng mã giảm giá', review_competitors: 'Theo dõi nhóm đối thủ', no_response: 'Chưa có đề xuất',
  recommended: 'Có khuyến nghị', scenario_only: 'Kịch bản mô phỏng', monitoring_only: 'Chỉ theo dõi', needs_cost_validation: 'Cần bổ sung giá vốn', needs_promotion_validation: 'Cần xác minh điều kiện khuyến mãi', constraint_blocked: 'Không đạt điều kiện lợi nhuận', insufficient_evidence: 'Chưa đủ dữ liệu',
  high: 'Cao', medium: 'Trung bình', low: 'Thấp',
  verified: 'Đã kiểm tra', seeded_cost_not_verified: 'Giá gốc đang là dữ liệu seed', unverified_cost_missing: 'Chưa có giá vốn', blocked_cost_missing: 'Thiếu giá vốn', blocked_promotion_terms_missing: 'Chưa xác minh điều kiện khuyến mãi', not_applicable: 'Không áp dụng', outlier_review_required: 'Cần kiểm tra giá ngoại lệ', market_below_margin_floor: 'Giá thị trường thấp hơn giá sàn', margin_floor_leaves_no_discount_room: 'Không còn dư địa giảm giá',
  same_product: 'Cùng sản phẩm', near_match: 'Gần tương đồng', substitute: 'Sản phẩm thay thế', not_enough_evidence: 'Chưa đủ dữ liệu',
  same_product_variant: 'Cùng dòng, khác quy cách',
  competitor_momentum_up: 'Sức bán của đối thủ tăng', competitor_price_down: 'Đối thủ giảm giá', competitor_promotion_started: 'Đối thủ bắt đầu khuyến mãi', high_competitive_pressure: 'Áp lực cạnh tranh cao', our_discount_below_market: 'Khuyến mãi thấp hơn thị trường', our_price_above_market: 'Giá cao hơn thị trường',
  competitive_pressure_score: 'Điểm áp lực cạnh tranh', discount_gap_pct: 'Chênh lệch khuyến mãi', peer_sales_momentum_pct: 'Đà bán của nhóm đối thủ', price_down_peer_count: 'Số đối thủ giảm giá', price_gap_pct: 'Chênh lệch giá', promotion_peer_count: 'Số đối thủ có khuyến mãi',
}
const label = (value?: string) => translations[value || ''] || (value || '').replaceAll('_', ' ')
const discountLabel = (value?: number) => value != null && Number.isFinite(Number(value)) && Number(value) >= 0.5 ? `Giảm ${Math.round(Number(value))}%` : 'Không khuyến mãi'
const suggestedValue = (recommendation: Recommendation, currency = 'VND') => {
  if (recommendation.recommendation_status === 'insufficient_evidence') return 'Chưa đề xuất'
  if (recommendation.recommendation_status === 'needs_cost_validation') return 'Chờ giá vốn'
  if (recommendation.action === 'use_voucher') return recommendation.recommended_discount_percent == null ? 'Chờ xác định' : `Giảm ${recommendation.recommended_discount_percent.toFixed(1)}%`
  if (recommendation.action === 'hold_price') return 'Giữ nguyên'
  if (recommendation.action === 'review_competitors') return 'Theo dõi, chưa đổi giá'
  return money(recommendation.recommended_price, currency)
}
const recommendationTitle = (recommendation: Recommendation) => {
  if (recommendation.recommendation_status === 'insufficient_evidence') return 'Chưa đủ dữ liệu để khuyến nghị'
  if (recommendation.recommendation_status === 'needs_cost_validation') return 'Cần bổ sung giá vốn'
  if (recommendation.recommendation_status === 'constraint_blocked') return 'Chưa đạt điều kiện lợi nhuận'
  return label(recommendation.action)
}
type PackItem = Pick<Product, 'price' | 'weight_g' | 'volume_ml' | 'quantity' | 'total_weight_g' | 'total_volume_ml' | 'package_ambiguous' | 'variation_count' | 'price_variant_ambiguous'>
const number = (value?: number) => value == null ? '—' : new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value)
const packageSummary = (item: PackItem) => {
  if (item.price_variant_ambiguous) return `Listing có ${item.variation_count || 'nhiều'} lựa chọn; giá hiển thị chưa gắn chắc chắn với một quy cách`
  if (item.package_ambiguous) return 'Có nhiều lựa chọn quy cách; cần xác nhận biến thể'
  if (item.total_weight_g) return item.quantity && item.quantity > 1 ? `${item.quantity} đơn vị × ${number(item.weight_g)} g = ${number(item.total_weight_g)} g` : `${number(item.total_weight_g)} g`
  if (item.total_volume_ml) return item.quantity && item.quantity > 1 ? `${item.quantity} đơn vị × ${number(item.volume_ml)} ml = ${number(item.total_volume_ml)} ml` : `${number(item.total_volume_ml)} ml`
  if (item.quantity && item.quantity > 1) return `${item.quantity} đơn vị trong một lượt mua`
  return 'Chưa trích xuất được quy cách'
}
const normalizedPrice = (item: PackItem) => {
  if (!item.price || item.package_ambiguous || item.price_variant_ambiguous) return null
  if (item.total_weight_g) return { value: item.price / item.total_weight_g * 100, basis: '100 g' }
  if (item.total_volume_ml) return { value: item.price / item.total_volume_ml * 100, basis: '100 ml' }
  if (item.quantity) return { value: item.price / item.quantity, basis: 'đơn vị' }
  return null
}
const basisLabel = (value?: string) => value === '100_g' ? '100 g' : value === '100_ml' ? '100 ml' : value === 'mỗi_đơn_vị' ? 'mỗi đơn vị' : 'chưa xác định'
const priceBaselineLabel = (value?: string) => value === 'peer_market_median' ? 'Trung vị cùng sản phẩm ở nhà phân phối khác' : value === 'own_history_median' ? 'Trung vị lịch sử của chính SKU' : value === 'listed_reference' ? 'Giá niêm yết tham khảo' : 'Chưa có base giá đủ dữ liệu'
const evidenceObject = (value?: string | Record<string, unknown>) => { if (!value) return {} as Record<string, unknown>; if (typeof value === 'object') return value; try { return JSON.parse(value) as Record<string, unknown> } catch { return {} as Record<string, unknown> } }
const ageInDays = (snapshot?: string) => {
  if (!snapshot) return null
  const parsed = new Date(`${snapshot}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return null
  return Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 86400000))
}
type RecommendationStats = { recommended: number; scenarios: number; monitoring: number; needsReview: number; insufficient: number }
type Page = 'overview' | 'sku' | 'alerts' | 'recommendations'
const pageFromHash = (): Page => {
  const value = window.location.hash.replace('#', '')
  return value === 'sku' || value === 'alerts' || value === 'recommendations' ? value : 'overview'
}

function App() {
  const [country, setCountry] = useState('vn')
  const [company, setCompany] = useState('richy_vietnam')
  const [companies, setCompanies] = useState<Company[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [totalProducts, setTotalProducts] = useState(0)
  const [globalAlerts, setGlobalAlerts] = useState<Alert[]>([])
  const [totalAlerts, setTotalAlerts] = useState(0)
  const [globalRecommendations, setGlobalRecommendations] = useState<Recommendation[]>([])
  const [recommendationStats, setRecommendationStats] = useState<RecommendationStats>({ recommended: 0, scenarios: 0, monitoring: 0, needsReview: 0, insufficient: 0 })
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
      const result = await api.products(country, undefined, search, company)
      setProducts(result.data || [])
      setTotalProducts(result.meta?.total_count ?? result.data?.length ?? 0)
      if (!selected || selected.country_code !== country || !result.data.some((item) => item.item_id === selected.item_id && item.shop_id === selected.shop_id)) setSelected(result.data[0] || null)
    } catch (err) { setError(err instanceof Error ? err.message : 'Không tải được dữ liệu') } finally { setLoading(false) }
  }
  useEffect(() => {
    let cancelled = false
    setCompany('')
    api.companies(country).then((result) => {
      if (cancelled) return
      const rows = result.data || []
      setCompanies(rows)
      setCompany(rows[0]?.company_id || '')
    }).catch(() => { if (!cancelled) { setCompanies([]); setError('Không tải được danh sách doanh nghiệp') } })
    return () => { cancelled = true }
  }, [country])
  useEffect(() => { if (company) { setSelected(null); void loadProducts() } }, [country, company])
  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  useEffect(() => {
    if (!company) { setGlobalAlerts([]); setTotalAlerts(0); setGlobalRecommendations([]); setRecommendationStats({ recommended: 0, scenarios: 0, monitoring: 0, needsReview: 0, insufficient: 0 }); return }
    let cancelled = false
    Promise.allSettled([
      api.alertsOverview(country, undefined, '', company),
      api.recommendationsOverview(country, undefined, 'recommended', 100, company),
      api.recommendationsOverview(country, undefined, 'scenario_only', 100, company),
      api.recommendationsOverview(country, undefined, 'monitoring_only', 100, company),
      api.recommendationsOverview(country, undefined, 'needs_cost_validation', 100, company),
      api.recommendationsOverview(country, undefined, 'needs_promotion_validation', 100, company),
      api.recommendationsOverview(country, undefined, 'constraint_blocked', 100, company),
      api.recommendationsOverview(country, undefined, 'insufficient_evidence', 1, company),
    ]).then(([alerts, recommended, scenarios, monitoring, needsCost, needsPromotion, blocked, insufficient]) => {
      if (cancelled) return
      setGlobalAlerts(alerts.status === 'fulfilled' ? alerts.value.data || [] : [])
      setTotalAlerts(alerts.status === 'fulfilled' ? alerts.value.meta?.total_count ?? alerts.value.data?.length ?? 0 : 0)
      const recommendedRows = recommended.status === 'fulfilled' ? recommended.value.data || [] : []
      const scenarioRows = scenarios.status === 'fulfilled' ? scenarios.value.data || [] : []
      const monitoringRows = monitoring.status === 'fulfilled' ? monitoring.value.data || [] : []
      const needsCostRows = needsCost.status === 'fulfilled' ? needsCost.value.data || [] : []
      const needsPromotionRows = needsPromotion.status === 'fulfilled' ? needsPromotion.value.data || [] : []
      const blockedRows = blocked.status === 'fulfilled' ? blocked.value.data || [] : []
      setGlobalRecommendations([...recommendedRows, ...scenarioRows, ...needsCostRows, ...needsPromotionRows, ...blockedRows, ...monitoringRows])
      setRecommendationStats({
        recommended: recommended.status === 'fulfilled' ? recommended.value.meta?.total_count ?? recommendedRows.length : 0,
        scenarios: scenarios.status === 'fulfilled' ? scenarios.value.meta?.total_count ?? scenarioRows.length : 0,
        monitoring: monitoring.status === 'fulfilled' ? monitoring.value.meta?.total_count ?? monitoringRows.length : 0,
        needsReview: (needsCost.status === 'fulfilled' ? needsCost.value.meta?.total_count ?? needsCostRows.length : 0) + (needsPromotion.status === 'fulfilled' ? needsPromotion.value.meta?.total_count ?? needsPromotionRows.length : 0) + (blocked.status === 'fulfilled' ? blocked.value.meta?.total_count ?? blockedRows.length : 0),
        insufficient: insufficient.status === 'fulfilled' ? insufficient.value.meta?.total_count ?? 0 : 0,
      })
    })
    return () => { cancelled = true }
  }, [country, company])
  useEffect(() => {
    if (!selected) { setDetail(null); return }
    let cancelled = false
    setDetail(null)
    Promise.allSettled([api.product(country, selected.shop_id, selected.item_id), api.signals(country, selected.shop_id, selected.item_id), api.peers(country, selected.shop_id, selected.item_id), api.alerts(country, selected.shop_id, selected.item_id), api.recommendation(country, selected.shop_id, selected.item_id)])
      .then(([product, signal, peers, alerts, recommendation]) => {
        if (cancelled) return
        const value = <T,>(result: PromiseSettledResult<{ data: T }>) => result.status === 'fulfilled' ? result.value.data : undefined
        const productData = value(product)
        if (!productData) { setError('SKU không còn trong bản dữ liệu hiện tại'); return }
        setDetail({ product: productData, signal: value(signal), peers: value(peers) || [], alerts: value(alerts) || [], recommendation: value(recommendation) })
      })
    return () => { cancelled = true }
  }, [selected, country])

  const stats = useMemo(() => {
    const avgDiscount = products.length ? products.reduce((sum, p) => sum + (p.discount_percent || 0), 0) / products.length : 0
    return { avgDiscount }
  }, [products])
  const latestSnapshot = detail?.signal?.snapshot_date || products[0]?.snapshot_date
  const dataAge = ageInDays(latestSnapshot)
  const dataIsStale = dataAge != null && dataAge > 2

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>Market IQ</strong><span>Hỗ trợ quyết định</span></div></div>
      <nav><button className={page === 'overview' ? 'active' : ''} onClick={() => navigate('overview')}><TrendingUp size={17} /> Tổng quan thị trường</button><button className={page === 'sku' ? 'active' : ''} onClick={() => navigate('sku')}><PackageSearch size={17} /> Phân tích SKU</button><button className={page === 'alerts' ? 'active' : ''} onClick={() => navigate('alerts')}><AlertTriangle size={17} /> Cảnh báo đối thủ <em>{totalAlerts}</em></button><button className={page === 'recommendations' ? 'active' : ''} onClick={() => navigate('recommendations')}><CircleDollarSign size={17} /> Khuyến nghị <em>{recommendationStats.recommended + recommendationStats.needsReview}</em></button></nav>
      <div className="sidebar-bottom"><div className={`status-dot ${dataIsStale ? 'stale' : ''}`}><span /> {dataIsStale ? 'Dữ liệu cần cập nhật' : 'Dữ liệu còn hiệu lực'}</div><small>Ngày dữ liệu gần nhất<br />{latestSnapshot || '—'}</small></div>
    </aside>
    <main className="main" onClick={(event) => { const target = event.target as HTMLElement; if (target.closest('.approve-button')) setApprovalOpen(true); if (target.closest('.product-row')) navigate('sku') }}>
      <header className="topbar"><div><p className="eyebrow">TRUNG TÂM ĐIỀU HÀNH / 05</p><h1>{page === 'overview' ? 'Tổng quan thị trường' : page === 'sku' ? 'Phân tích SKU' : page === 'alerts' ? 'Cảnh báo đối thủ' : 'Khuyến nghị'}</h1></div><div className="top-actions"><select value={country} onChange={(e) => setCountry(e.target.value)}><option value="vn">🇻🇳 Việt Nam</option><option value="id">🇮🇩 Indonesia</option></select><select className="company-select" value={company} onChange={(event) => setCompany(event.target.value)} disabled={!companies.length}>{companies.map((item) => <option key={item.company_id} value={item.company_id}>{item.company_name} · {item.sku_count} SKU</option>)}</select><button className="icon-button" onClick={() => void loadProducts()} title="Làm mới dữ liệu"><RefreshCw size={17} /></button><div className="avatar">MA</div></div></header>
      {error && <div className="error-banner"><AlertTriangle size={16} /> {error}<button onClick={() => setError('')}>×</button></div>}
      {dataIsStale && <div className="stale-banner"><AlertTriangle size={16} /><span>Dữ liệu gần nhất là ngày {latestSnapshot}, đã cách hiện tại {dataAge} ngày. Cảnh báo và khuyến nghị chỉ phản ánh snapshot này, không phải trạng thái thị trường theo thời gian thực.</span></div>}
      <section className="metric-grid"><Metric icon={<Store />} label="SKU của hãng" value={loading ? '…' : totalProducts.toLocaleString('vi-VN')} hint={companies.find((item) => item.company_id === company)?.company_name || 'Đang chọn hãng'} /><Metric icon={<CircleDollarSign />} label="Mức giảm giá trung bình" value={`${stats.avgDiscount.toFixed(1)}%`} hint="trong dữ liệu hiện tại" /><Metric icon={<ShieldCheck />} label="Có khuyến nghị rõ ràng" value={recommendationStats.recommended.toLocaleString('vi-VN')} hint={`${recommendationStats.needsReview} trường hợp cần bổ sung dữ liệu`} good /><Metric icon={<AlertTriangle />} label="Cảnh báo tại snapshot mới nhất" value={totalAlerts.toString()} hint={latestSnapshot || 'chưa có ngày dữ liệu'} /></section>
      {page === 'overview' && <div className="workspace"><section className="panel catalogue"><div className="panel-heading"><div><p className="eyebrow">DANH MỤC SẢN PHẨM</p><h2>Sản phẩm cần theo dõi</h2></div><div className="search"><Search size={16} /><input placeholder="Tìm theo tên sản phẩm" value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void loadProducts()} /></div></div>{loading ? <div className="loading"><LoaderCircle className="spin" /> Đang tải dữ liệu sản phẩm…</div> : <div className="product-list">{products.map((product) => <button key={`${product.shop_id}-${product.item_id}`} className={`product-row ${selected?.item_id === product.item_id && selected?.shop_id === product.shop_id ? 'selected' : ''}`} onClick={() => setSelected(product)}><div className="product-thumb">{product.image_url ? <img src={product.image_url} /> : <PackageSearch size={19} />}</div><div className="product-copy"><strong>{product.product_name || 'Sản phẩm chưa có tên'}</strong><span>{product.brand || product.shop_name || '—'} · SKU {product.item_id}</span></div><div className="product-price"><strong>{money(product.price, product.currency)}</strong><span>{discountLabel(product.discount_percent)}</span></div><ChevronRight size={16} className="chevron" /></button>)}{!products.length && !loading && <div className="empty">Không tìm thấy sản phẩm trong phạm vi này.</div>}</div>}</section>
        <section className="panel copilot"><div className="panel-heading"><div><p className="eyebrow">TRỢ LÝ AI</p><h2>Hỏi về thị trường</h2></div><div className="online"><span /> Đang hoạt động</div></div><div className="copilot-hero"><div className="bot-orb"><Bot size={25} /></div><p>Hỏi về giá, nhóm đối thủ, cảnh báo hoặc chiến lược cho SKU đang chọn.</p></div><ChatPanel selected={selected} /> </section></div>}
      {page === 'overview' && detail && <Detail detail={detail} />}
      {page === 'sku' && <section className="panel sku-selector"><div><span>SKU đang phân tích</span><strong>{selected?.product_name || 'Chưa chọn sản phẩm'}</strong></div><select value={selected ? `${selected.shop_id}:${selected.item_id}` : ''} onChange={(event) => { const [shop, item] = event.target.value.split(':').map(Number); const next = products.find((product) => product.shop_id === shop && product.item_id === item); if (next) setSelected(next) }}><option value="" disabled>Chọn SKU</option>{products.map((product) => <option key={`${product.shop_id}:${product.item_id}`} value={`${product.shop_id}:${product.item_id}`}>{product.shop_name} · {product.product_name}</option>)}</select></section>}
      {page === 'sku' && (detail ? <Detail detail={detail} /> : <PageEmpty message="Chọn một sản phẩm để mở phần phân tích SKU." />)}
      {page === 'alerts' && <AlertCenterPage alerts={globalAlerts} total={totalAlerts} onSelect={async (alert) => { let product = products.find((item) => item.item_id === alert.source_item_id && item.shop_id === alert.source_shop_id); if (!product && alert.source_item_id && alert.source_shop_id) { try { product = (await api.product(country, alert.source_shop_id, alert.source_item_id)).data } catch { setError('Không tải được SKU từ cảnh báo') } } if (product) { setSelected(product); navigate('sku') } }} />}
      {page === 'recommendations' && <RecommendationCenterPage recommendations={globalRecommendations} products={products} stats={recommendationStats} onReview={() => setApprovalOpen(true)} />}
      {page !== 'overview' && <section className="panel page-copilot"><div className="panel-heading"><div><p className="eyebrow">TRỢ LÝ AI</p><h2>Hỏi về nội dung đang xem</h2></div><div className="online"><span /> Đang hoạt động</div></div><ChatPanel selected={selected} /></section>}
      {approvalOpen && <ApprovalModal onClose={() => setApprovalOpen(false)} />}
    </main>
    {chatOpen && <button className="mobile-chat" onClick={() => setChatOpen(false)}><MessageSquare size={17} /> Trợ lý AI</button>}
  </div>
}

function Metric({ icon, label: title, value, hint, good }: { icon: React.ReactNode; label: string; value: string; hint: string; good?: boolean }) { return <div className="metric"><div className="metric-icon">{icon}</div><div><span>{title}</span><strong>{value}</strong><small className={good ? 'good' : ''}>{hint}</small></div></div> }

function PageEmpty({ message }: { message: string }) { return <section className="panel page-empty"><PackageSearch size={28} /><h2>Chưa có SKU được chọn</h2><p>{message}</p></section> }

function AlertPage({ alerts }: { alerts: Alert[] }) { return <section className="panel page-panel"><div className="panel-heading"><div><p className="eyebrow">TRUNG TÂM CẢNH BÁO</p><h2>Cảnh báo đối thủ của SKU đang chọn</h2></div><span className="count-pill alert-count">{alerts.length} cảnh báo</span></div>{alerts.length ? alerts.map((alert, index) => <div className="alert-row alert-row-large" key={`${alert.alert_type}-${index}`}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={16} /></div><div><strong>{label(alert.alert_type)}</strong><span>{label(alert.metric_name)} · giá trị {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} · ngưỡng {alert.threshold ?? '—'}</span><small>{alert.snapshot_date} · đã có dữ liệu giải thích</small></div><b className={`severity-text ${alert.severity}`}>{label(alert.severity)}</b></div>) : <div className="empty">Chưa có cảnh báo hoặc chưa đủ dữ liệu để cảnh báo.</div>}</section> }

function RecommendationPage({ recommendation, product }: { recommendation: Recommendation; product: Product }) { return <section className="panel page-panel recommendation-page"><div className="panel-heading"><div><p className="eyebrow">HỖ TRỢ RA QUYẾT ĐỊNH</p><h2>Xem xét khuyến nghị</h2></div><span className={`badge ${recommendation.priority}`}>{label(recommendation.priority)}</span></div><div className="recommendation recommendation-inline"><div className="recommendation-icon"><Sparkles size={19} /></div><div className="recommendation-body"><p className="eyebrow">SKU {product.item_id} · độ tin cậy {label(recommendation.confidence).toLowerCase()}</p><h3>{label(recommendation.action)}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Giá hiện tại<strong>{money(recommendation.source_price, product.currency)}</strong></span><span>Đề xuất<strong>{suggestedValue(recommendation, product.currency)}</strong></span><span>Điều kiện an toàn<strong>{label(recommendation.constraint_status)}</strong></span></div></div><button className="approve-button">Xem xét <ChevronRight size={16} /></button></div></section> }

function AlertCenterPage({ alerts, total, onSelect }: { alerts: Alert[]; total: number; onSelect: (alert: Alert) => void }) { return <section className="panel page-panel"><div className="panel-heading"><div><p className="eyebrow">TRUNG TÂM CẢNH BÁO</p><h2>Cảnh báo theo hãng và kênh phân phối</h2><span className="section-caption">Chỉ hiển thị {alerts.length}/{total} cảnh báo còn đúng ở snapshot mới nhất của từng SKU</span></div><span className="count-pill alert-count">{total} cảnh báo</span></div>{alerts.length ? alerts.map((alert, index) => <button className="alert-row alert-row-large alert-button" key={`${alert.alert_type}-${alert.source_item_id}-${index}`} onClick={() => onSelect(alert)}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={16} /></div><div><strong>{label(alert.alert_type)} · SKU {alert.source_item_id}</strong><span>{label(alert.metric_name)} · giá trị {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} · ngưỡng {alert.threshold ?? '—'}</span><small>{alert.target_seller_entity_name ? `Đối chiếu với ${alert.target_seller_entity_name} · ` : ''}{alert.snapshot_date} · nhấn để mở phân tích SKU</small></div><b className={`severity-text ${alert.severity}`}>{label(alert.severity)}</b></button>) : <div className="empty">Không có cảnh báo nào còn đúng ở snapshot mới nhất, hoặc dữ liệu chưa đủ để cảnh báo.</div>}</section> }

function RecommendationCenterPage({ recommendations, products, stats, onReview }: { recommendations: Recommendation[]; products: Product[]; stats: RecommendationStats; onReview: () => void }) {
  return <section className="panel page-panel">
    <div className="panel-heading"><div><p className="eyebrow">HỖ TRỢ RA QUYẾT ĐỊNH</p><h2>Khuyến nghị và kịch bản</h2></div><span className="count-pill">{stats.recommended + stats.scenarios + stats.needsReview}</span></div>
    <div className="recommendation-summary"><div><strong>{stats.recommended}</strong><span>Có khuyến nghị hành động</span></div><div><strong>{stats.scenarios}</strong><span>Kịch bản dùng giá gốc seed</span></div><div><strong>{stats.monitoring}</strong><span>Chỉ theo dõi sản phẩm thay thế</span></div><div><strong>{stats.needsReview}</strong><span>Cần bổ sung dữ liệu</span></div><div><strong>{stats.insufficient}</strong><span>Chưa đủ dữ liệu đối thủ</span></div></div>
    <p className="recommendation-note">Kịch bản seed và nhóm chỉ theo dõi không được tính là khuyến nghị thực thi.</p>
    {recommendations.length ? recommendations.map((recommendation, index) => {
      const product = products.find((item) => item.item_id === recommendation.source_item_id && item.shop_id === recommendation.source_shop_id)
      const monitoring = recommendation.recommendation_status === 'monitoring_only'
      const scenario = recommendation.recommendation_status === 'scenario_only'
      const needsInput = !monitoring && !scenario && recommendation.recommendation_status !== 'recommended'
      return <div className={`recommendation recommendation-list-item ${needsInput ? 'needs-input' : ''} ${monitoring ? 'monitoring' : ''} ${scenario ? 'scenario' : ''}`} key={`${recommendation.source_item_id}-${index}`}><div className="recommendation-icon"><Sparkles size={18} /></div><div className="recommendation-body"><p className="eyebrow">SKU {recommendation.source_item_id} · {label(recommendation.recommendation_status)}</p><h3>{needsInput || monitoring || scenario ? label(recommendation.recommendation_status) : label(recommendation.action)}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Giá hiện tại<strong>{money(recommendation.source_price, product?.currency || recommendation.currency)}</strong></span>{scenario && <span>Giá gốc seed<strong>{money(recommendation.cost_value, product?.currency || recommendation.currency)}</strong></span>}<span>Đề xuất<strong>{suggestedValue(recommendation, product?.currency || recommendation.currency)}</strong></span><span>Độ tin cậy<strong>{label(recommendation.confidence)}</strong></span></div></div>{!monitoring && !scenario && <button className="approve-button" onClick={onReview}>{needsInput ? 'Xem điều kiện' : 'Xem xét'} <ChevronRight size={16} /></button>}</div>
    }) : <div className="empty">Chưa có khuyến nghị hoặc kịch bản nào để xem.</div>}
  </section>
}

function ApprovalModal({ onClose }: { onClose: () => void }) { const [reason, setReason] = useState(''); const [submitted, setSubmitted] = useState(false); return <div className="modal-backdrop" role="presentation" onClick={onClose}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="approval-title" onClick={(event) => event.stopPropagation()}><div className="modal-header"><div><p className="eyebrow">QUY TRÌNH XEM XÉT</p><h2 id="approval-title">Xem xét hành động được đề xuất</h2></div><button className="modal-close" onClick={onClose}>×</button></div>{submitted ? <div className="modal-success"><ShieldCheck size={23} /><h3>Đã lưu kết quả xem xét trên bản thử nghiệm</h3><p>Đây là bản xem trước MVP, chưa kết nối với chức năng thay đổi giá thật.</p><button className="approve-button" onClick={onClose}>Đóng</button></div> : <><p className="modal-copy">Kiểm tra dữ liệu giải thích và ghi chú lý do trước khi đưa hành động vào kế hoạch xử lý.</p><textarea placeholder="Lý do hoặc ghi chú (không bắt buộc)" value={reason} onChange={(event) => setReason(event.target.value)} /><div className="modal-actions"><button className="secondary-button" onClick={onClose}>Hủy</button><button className="approve-button" onClick={() => setSubmitted(true)}>Tạo kế hoạch hành động <ChevronRight size={16} /></button></div></>}</div></div> }

function Detail({ detail }: { detail: { product: Product; signal?: Signal; peers: Peer[]; alerts: Alert[]; recommendation?: Recommendation } }) {
  const { product, signal, peers, alerts, recommendation } = detail
  const pressure = String(signal?.competitive_pressure_level || 'low')
  const canReview = recommendation && !['insufficient_evidence', 'monitoring_only', 'scenario_only'].includes(recommendation.recommendation_status)
  const sourceNormalized = normalizedPrice(product)
  const comparablePeers = peers.filter((peer) => normalizedPrice(peer)?.basis === sourceNormalized?.basis)
  const priceBarMax = Math.max(product.price || 1, product.price_original || 1, Number(signal?.source_historical_median_price) || 1, Number(signal?.peer_median_price) || 1)
  const costAssumption = evidenceObject(recommendation?.evidence).cost_assumption as Record<string, unknown> | undefined
  return <section className="detail">
    <div className="detail-header"><div><p className="eyebrow">PHÂN TÍCH SKU / {product.item_id}</p><h2>{product.product_name}</h2><span className="muted">Hãng {product.company_name || product.brand || 'Chưa xác định'} · Nhà phân phối {product.seller_entity_name || product.shop_name} · dữ liệu ngày {product.snapshot_date}</span></div><a className="outline-button" href={product.url} target="_blank" rel="noreferrer">Mở trang bán <ArrowUpRight size={15} /></a></div>
    <div className="detail-grid">
      <div className="panel sku-card"><div className="sku-card-top"><div className="large-thumb">{product.image_url ? <img src={product.image_url} /> : <PackageSearch />}</div><div><span className="eyebrow">GIÁ BÁN HIỆN TẠI</span><h3>{money(product.price, product.currency)}</h3><p>{discountLabel(product.discount_percent)} · {product.rating?.toFixed(1) || '—'} điểm đánh giá</p><p className="package-line">{packageSummary(product)}</p></div></div><div className="price-bars"><Bar label="Giá niêm yết" value={product.price_original} max={priceBarMax} color="gray" /><Bar label="Trung vị lịch sử" value={signal?.source_historical_median_price} max={priceBarMax} color="purple" /><Bar label="Giá SKU hiện tại" value={product.price} max={priceBarMax} color="blue" /><Bar label="Base thị trường cùng quy cách" value={Number(signal?.peer_median_price)} max={priceBarMax} color="orange" /></div></div>
      <div className="panel signal-card"><div className="panel-heading compact"><div><p className="eyebrow">TÍN HIỆU THỊ TRƯỜNG</p><h3>Vị thế giá và hoạt động cạnh tranh</h3></div><span className={`badge ${pressure}`}>{label(pressure)}</span></div><div className="signal-value">{signal?.competitive_pressure_score == null ? '—' : `${(Number(signal.competitive_pressure_score) * 100).toFixed(0)} / 100`}<small>Độ tin cậy {label(signal?.signal_confidence).toLowerCase()} · {signal?.peer_count || 0} peer giá · {signal?.benchmark_peer_count || 0} peer theo dõi</small></div><div className="signal-row"><span>Chênh lệch giá trên cùng quy cách</span><strong>{pct(signal?.price_gap_pct)}</strong></div><div className="signal-row"><span>Đối thủ thay thế đang giảm giá</span><strong>{signal?.price_down_peer_count || 0}</strong></div><div className="signal-row"><span>Đối thủ thay thế mở khuyến mãi</span><strong>{signal?.promotion_peer_count || 0}</strong></div></div>
    </div>
    <section className="panel comparison-audit"><div className="panel-heading compact"><div><p className="eyebrow">CƠ SỞ SO SÁNH KHÁCH QUAN</p><h3>Kiểm tra hãng, nhà phân phối, biến thể, quy cách và base giá</h3></div><span className={`badge ${product.package_ambiguous || product.price_variant_ambiguous || !sourceNormalized ? 'medium' : 'low'}`}>{product.price_variant_ambiguous ? 'Không dùng để so giá' : product.package_ambiguous || !sourceNormalized ? 'Cần kiểm tra' : 'Có thể quy đổi'}</span></div><div className="audit-grid"><div><span>Hãng / chủ sở hữu thương hiệu</span><strong>{product.company_name || 'Chưa xác định'}</strong></div><div><span>Nhà bán / nhà phân phối</span><strong>{product.seller_entity_name || product.shop_name || 'Chưa xác định'}</strong></div><div><span>Dòng sản phẩm</span><strong>{product.family_signature || label(product.product_type)}</strong></div><div><span>Biến thể nhận diện được</span><strong>{product.variant_signature || 'Chưa xác định rõ từ tên sản phẩm'}</strong></div><div><span>Quy cách SKU gốc</span><strong>{packageSummary(product)}</strong></div><div><span>Số lựa chọn trên listing</span><strong>{product.variation_count || 0}</strong></div><div><span>Đơn vị chuẩn hóa</span><strong>{basisLabel(signal?.price_comparison_basis)}</strong></div><div><span>Giá SKU sau chuẩn hóa</span><strong>{signal?.source_normalized_price == null ? '—' : `${money(signal.source_normalized_price, product.currency)} / ${basisLabel(signal.price_comparison_basis)}`}</strong></div><div><span>Giá niêm yết tham khảo</span><strong>{money(signal?.source_list_price ?? product.price_original, product.currency)}</strong></div><div><span>Trung vị lịch sử SKU</span><strong>{money(signal?.source_historical_median_price, product.currency)} · {signal?.source_price_observation_count || 0} quan sát</strong></div><div><span>Base giá phân tích</span><strong>{money(signal?.price_baseline_value, product.currency)} · {priceBaselineLabel(signal?.price_baseline_type)}</strong></div><div><span>Mức sử dụng</span><strong>{signal?.price_baseline_actionable ? 'Đủ chuẩn làm tham chiếu hành động, vẫn cần giá vốn' : 'Chỉ tham khảo; không tự động đổi giá'}</strong></div><div><span>Trung vị kênh phân phối/đối thủ</span><strong>{signal?.peer_median_normalized_price == null ? '—' : `${money(signal.peer_median_normalized_price, product.currency)} / ${basisLabel(signal.price_comparison_basis)}`}</strong></div></div><p className="audit-note">Giá niêm yết không được coi là giá vốn. Base giá ưu tiên trung vị cùng sản phẩm ở nhà phân phối khác; nếu chưa có peer giá hợp lệ, hệ thống chỉ hiển thị trung vị lịch sử hoặc giá niêm yết như dữ liệu tham khảo và không tạo hành động đổi giá.</p></section>
    {recommendation && costAssumption?.cost_source === 'seeded_scenario' && <section className="panel seed-cost-panel"><div className="panel-heading compact"><div><p className="eyebrow">GIÁ GỐC GIẢ ĐỊNH / DỮ LIỆU SEED</p><h3>Kịch bản chi phí để thử recommendation</h3></div><span className="badge medium">Không phải giá vốn thật</span></div><div className="audit-grid"><div><span>Giá gốc seed</span><strong>{money(recommendation.cost_value, product.currency)}</strong></div><div><span>Dải giả định</span><strong>{money(Number(costAssumption.cost_low), product.currency)} – {money(Number(costAssumption.cost_high), product.currency)}</strong></div><div><span>Tỷ lệ seed trên base</span><strong>{Number(costAssumption.cost_seed_pct).toFixed(0)}%</strong></div><div><span>Base dùng để seed</span><strong>{money(Number(costAssumption.cost_reference_price), product.currency)} · {priceBaselineLabel(String(costAssumption.baseline_type || ''))}</strong></div><div><span>Biên lợi nhuận tối thiểu giả định</span><strong>{recommendation.margin_min_pct?.toFixed(0) || '—'}%</strong></div><div><span>Giá sàn theo kịch bản</span><strong>{money(recommendation.price_floor, product.currency)}</strong></div><div><span>Độ tin cậy của giá gốc</span><strong>{costAssumption.cost_confidence === 'low' ? 'Thấp' : 'Rất thấp'}</strong></div><div><span>Phạm vi sử dụng</span><strong>Chỉ mô phỏng; cần thay bằng giá vốn ERP/kế toán trước khi thực thi</strong></div></div></section>}
    <div className="detail-grid lower">
      <section className="panel"><div className="panel-heading compact"><div><p className="eyebrow">SẢN PHẨM TƯƠNG ĐỒNG</p><h3>Nhóm kênh phân phối và đối thủ so sánh</h3><span className="section-caption">{comparablePeers.length}/{peers.length} sản phẩm có thể quy đổi về cùng đơn vị giá</span></div><span className="count-pill">{peers.length}</span></div>{peers.length ? peers.map((peer) => { const peerNormalized = normalizedPrice(peer); const sameBasis = peerNormalized && peerNormalized.basis === sourceNormalized?.basis; return <div className="peer-row peer-row-detailed" key={`${peer.target_shop_id}-${peer.target_item_id}`}><div><strong>{peer.product_name || `SKU ${peer.target_item_id}`}</strong><span>{peer.seller_entity_name || peer.company_name || peer.brand || '—'} · {peer.company_id === product.company_id ? 'Cùng hãng, khác nhà phân phối' : 'Khác hãng'} · {label(peer.relation)} · độ tin cậy {label(peer.confidence).toLowerCase()}</span><small>{peer.family_signature ? `Dòng ${peer.family_signature} · ` : ''}{packageSummary(peer)}{peer.variant_signature ? ` · Biến thể: ${peer.variant_signature}` : ''}</small></div><div className="peer-price-analysis"><strong>{money(peer.price, peer.currency)}</strong><span>{sameBasis ? `${money(peerNormalized.value, peer.currency)} / ${peerNormalized.basis}` : 'Chưa thể quy đổi cùng đơn vị'}</span></div><span className="match-score">{(peer.match_score * 100).toFixed(0)}%</span></div> }) : <div className="empty">Chưa đủ dữ liệu để xác định sản phẩm đối thủ tương đồng.</div>}</section>
      <section className="panel"><div className="panel-heading compact"><div><p className="eyebrow">CẢNH BÁO ĐỐI THỦ</p><h3>Tại snapshot mới nhất</h3></div><span className="count-pill alert-count">{alerts.length}</span></div>{alerts.length ? alerts.slice(0, 4).map((alert, i) => <div className="alert-row" key={`${alert.alert_type}-${i}`}><div className={`alert-icon ${alert.severity}`}><AlertTriangle size={15} /></div><div><strong>{label(alert.alert_type)}</strong><span>{label(alert.metric_name)} · {alert.metric_value == null ? '—' : alert.metric_value.toFixed(1)} (ngưỡng {alert.threshold ?? '—'})</span></div><small>{label(alert.severity)}</small></div>) : <div className="empty">Không có cảnh báo nào còn đúng tại snapshot mới nhất.</div>}</section>
    </div>
    {recommendation && <section className={`recommendation ${recommendation.recommendation_status === 'insufficient_evidence' ? 'insufficient' : ''}`}><div className="recommendation-icon"><Sparkles size={19} /></div><div className="recommendation-body"><p className="eyebrow">TRẠNG THÁI KHUYẾN NGHỊ · {label(recommendation.recommendation_status)}</p><h3>{recommendationTitle(recommendation)}</h3><p>{recommendation.recommendation_text}</p><div className="recommendation-meta"><span>Base giá sử dụng<strong>{money(signal?.price_baseline_value, product.currency)}</strong></span><span>Độ tin cậy<strong>{label(recommendation.confidence)}</strong></span><span>Đề xuất<strong>{suggestedValue(recommendation, product.currency)}</strong></span><span>Điều kiện an toàn<strong>{label(recommendation.constraint_status)}</strong></span></div></div>{canReview && <button className="approve-button">{recommendation.recommendation_status === 'recommended' ? 'Xem xét' : 'Xem điều kiện'} <ChevronRight size={16} /></button>}</section>}
  </section>
}

function Bar({ label: title, value, max, color }: { label: string; value?: number; max: number; color: string }) { return <div className="bar-row"><span>{title}</span><div className="bar-track"><i className={color} style={{ width: `${Math.min(100, ((value || 0) / max) * 100)}%` }} /></div><strong>{value == null ? '—' : value.toLocaleString('vi-VN')}</strong></div> }

function ChatPanel({ selected }: { selected: Product | null }) {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const ask = async (text = message) => { if (!text.trim()) return; setBusy(true); setReply(''); try { const result = await api.chat(text, selected || {}); setReply(String(result.answer || 'Không có câu trả lời.')) } catch (err) { setReply(err instanceof Error ? err.message : 'Trợ lý AI không phản hồi') } finally { setBusy(false); setMessage('') } }
  return <div className="chat"><div className="suggestions"><button onClick={() => void ask('Tóm tắt thị trường cho SKU đang chọn')}>Tóm tắt SKU này</button><button onClick={() => void ask('Đối thủ nào đang gây áp lực?')}>Tìm nguồn áp lực</button><button onClick={() => void ask('Đề xuất giá và khuyến mãi')}>Đề xuất hành động</button></div>{reply && <div className="chat-reply"><Bot size={16} /><p>{reply}</p></div>}<div className="chat-input"><input placeholder="Nhập câu hỏi…" value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void ask()} /><button onClick={() => void ask()} disabled={busy} title="Gửi câu hỏi">{busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUpRight size={17} />}</button></div><small className="privacy"><ShieldCheck size={12} /> Chỉ đọc dữ liệu · không thay đổi trang bán</small></div>
}

export default App
