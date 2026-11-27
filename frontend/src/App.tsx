import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { HashRouter, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Bot, ChevronRight, FileText, LayoutDashboard, Settings, UploadCloud, Wifi, WifiOff, Send, Trash2, Pencil, X, Check, ChevronLeft, ChevronRight as ChevronRightIcon } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, apiBaseUrl, downloadReport, setApiBaseUrl, setPairingToken } from './services/api'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

type Invoice = {
  id: number
  invoice_number?: string
  invoice_date?: string
  vendor_name?: string
  grand_total?: number
  total_tax?: number
  validation_status?: string
  processing_status?: string
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <Shell />
      </HashRouter>
    </QueryClientProvider>
  )
}

function Shell() {
  const [connected, setConnected] = useState<boolean | null>(null)
  const navigate = useNavigate()
  const nav = [
    ['/', 'Dashboard', LayoutDashboard],
    ['/upload', 'Upload invoice', UploadCloud],
    ['/history', 'Invoices', FileText],
    ['/analytics', 'Analytics', BarChart3],
    ['/assistant', 'AI assistant', Bot],
    ['/settings', 'Settings', Settings],
  ] as const
  async function connect() {
    if (!apiBaseUrl) {
      const backendUrl = window.prompt('Enter the backend API URL (remote backends must use HTTPS).')
      if (!backendUrl) return
      try {
        setApiBaseUrl(backendUrl)
      } catch (error) {
        window.alert(error instanceof Error ? error.message : 'The backend URL is invalid.')
        return
      }
    }
    const token = window.prompt('Enter the backend pairing token.')
    if (!token) return
    setPairingToken(token.trim())
    try {
      await api('/api/system/status')
      setConnected(true)
      queryClient.invalidateQueries()
    } catch (error) {
      setPairingToken('')
      setConnected(false)
      window.alert(error instanceof Error ? error.message : 'Could not connect. Check the pairing token, backend, and browser local-network permission.')
    }
  }
  return (
    <div className="min-h-screen bg-[#f4f6fb] text-slate-900">
      <aside className="fixed left-0 top-0 z-20 hidden h-screen w-64 border-r border-slate-800 bg-[#10182a] px-4 py-6 md:block">
        <button className="mb-9 flex w-full items-center gap-3 px-2" onClick={() => navigate('/')} aria-label="Go to dashboard">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-500 text-lg font-bold text-white">F</span>
          <span className="text-left"><span className="block font-semibold text-white">FinSightAI</span><span className="block text-xs text-slate-400">Invoice intelligence</span></span>
        </button>
        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Workspace</p>
        <nav className="space-y-1" aria-label="Main navigation">
          {nav.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} className={({isActive}) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${isActive ? 'bg-indigo-500/15 font-medium text-indigo-200' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <Icon size={18} /> {label}
            </NavLink>
          ))}
        </nav>
        <button onClick={connect} className="absolute bottom-6 left-4 right-4 flex items-center justify-between rounded-lg border border-slate-700 px-3 py-3 text-sm text-slate-300 hover:bg-white/5">
          <span className="flex items-center gap-2">{connected ? <Wifi size={16} className="text-emerald-400"/> : <WifiOff size={16}/>} {connected === true ? 'Backend connected' : 'Connect backend'}</span>
          <ChevronRight size={16}/>
        </button>
      </aside>
      <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:hidden">
        <div className="flex items-center justify-between">
          <button className="flex items-center gap-2 font-semibold" onClick={() => navigate('/')}><span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white">F</span>FinSightAI</button>
          <button onClick={connect} className="flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium">{connected ? <Wifi size={14} className="text-emerald-600"/> : <WifiOff size={14}/>} {connected ? 'Connected' : 'Connect'}</button>
        </div>
        <nav className="mt-3 flex gap-1 overflow-x-auto pb-1" aria-label="Mobile navigation">
          {nav.map(([to, label, Icon]) => <NavLink key={to} to={to} className={({isActive}) => `flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs ${isActive ? 'bg-indigo-50 font-semibold text-indigo-700' : 'text-slate-500'}`}><Icon size={14}/>{label}</NavLink>)}
        </nav>
      </div>
      <main className="md:ml-64"><div className="mx-auto max-w-[1440px] p-4 md:p-8">
        <Routes>
          <Route path="/" element={<Overview/>}/>
          <Route path="/upload" element={<UploadPage/>}/>
          <Route path="/history" element={<HistoryPage/>}/>
          <Route path="/analytics" element={<AnalyticsPage/>}/>
          <Route path="/assistant" element={<AssistantPage/>}/>
          <Route path="/settings" element={<SettingsPage/>}/>
        </Routes>
      </div></main>
    </div>
  )
}

function PageHeader({title, subtitle}:{title:string;subtitle:string}) {
  return <header className="mb-7"><p className="mb-2 text-xs font-semibold uppercase tracking-[0.15em] text-indigo-600">FinSightAI / Workspace</p><h1 className="text-3xl font-bold tracking-tight text-slate-900">{title}</h1><p className="mt-1 text-sm text-slate-500">{subtitle}</p></header>
}
function PageLoading() { return <div className="rounded-xl border bg-white p-8 text-center text-slate-500">Loading…</div> }
function PageError({error}:{error:Error}) { return <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">Unable to load the local backend. {error.message}</div> }
function ChartCard({title, children}:{title:string;children:ReactNode}) { return <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="mb-4 font-semibold">{title}</h2>{children}</article> }

function Overview() {
  const navigate = useNavigate()
  const {data, isLoading, error} = useQuery({queryKey:['overview'], queryFn:()=>api<any>('/api/analytics/overview')})
  if (isLoading) return <PageLoading/>
  if (error) return <PageError error={error as Error}/>
  const s = data.summary || {}
  const cards = [['Total verified spend',`₹${Number(s.total_expenses||0).toLocaleString('en-IN')}`],['Invoices processed',s.invoice_count||0],['Verified invoices',s.total_invoices||0],['Tax paid',`₹${Number(s.total_tax||0).toLocaleString('en-IN')}`],['Average invoice',`₹${Number(s.average_invoice||0).toLocaleString('en-IN')}`],['Needs attention',s.needs_attention||0]]
  return <div className="space-y-6">
    <PageHeader title="Financial overview" subtitle="A real-time view of verified expenses, taxes, and invoice processing"/>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">{cards.map(([label,value],index)=><article key={label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><p className="text-xs font-medium text-slate-500">{label}</p><span className={`h-2 w-2 rounded-full ${index===5?'bg-amber-400':'bg-indigo-500'}`}/></div><p className="mt-3 text-xl font-bold tracking-tight text-slate-900">{value}</p><p className="mt-1 text-[11px] text-slate-400">{index===5?'Review required':'Verified records only'}</p></article>)}</div>
    <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
      <ChartCard title="Monthly expenditure"><ResponsiveContainer width="100%" height={290}><BarChart data={data.monthly} margin={{top:8,right:8,left:0,bottom:0}}><CartesianGrid stroke="#eef0f5" vertical={false}/><XAxis dataKey="month" axisLine={false} tickLine={false}/><YAxis axisLine={false} tickLine={false}/><Tooltip formatter={(value)=>`₹${Number(value).toLocaleString('en-IN')}`}/><Bar dataKey="amount" fill="#5969d8" radius={[5,5,0,0]} maxBarSize={42}/></BarChart></ResponsiveContainer></ChartCard>
      <ChartCard title="Expense mix"><ResponsiveContainer width="100%" height={290}><PieChart><Pie data={data.categories} dataKey="amount" nameKey="category" innerRadius={62} outerRadius={98} paddingAngle={3} fill="#5969d8"/><Tooltip formatter={(value)=>`₹${Number(value).toLocaleString('en-IN')}`}/><Legend/></PieChart></ResponsiveContainer></ChartCard>
    </div>
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-slate-900">Recent invoices</h2><p className="mt-1 text-xs text-slate-500">Latest activity across your invoice records</p></div><button onClick={()=>navigate('/history')} className="text-sm font-semibold text-indigo-700">View all invoices</button></div>
      <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>{['Invoice','Vendor','Date','Amount','Status'].map(label=><th key={label} className="px-5 py-3 font-medium">{label}</th>)}</tr></thead><tbody>{(data.recent||[]).map((row:Invoice)=><tr key={row.id} className="border-t border-slate-100"><td className="px-5 py-3 font-medium">{row.invoice_number||`Invoice ${row.id}`}</td><td className="px-5 py-3">{row.vendor_name||'Unknown vendor'}</td><td className="px-5 py-3 text-slate-500">{row.invoice_date||'—'}</td><td className="px-5 py-3 font-medium">₹{Number(row.grand_total||0).toLocaleString('en-IN')}</td><td className="px-5 py-3"><span className={`rounded-full px-2.5 py-1 text-xs ${row.validation_status==='Verified'?'bg-emerald-50 text-emerald-700':'bg-amber-50 text-amber-700'}`}>{row.validation_status||'Needs review'}</span></td></tr>)}</tbody></table>{!data.recent?.length&&<p className="p-8 text-center text-sm text-slate-500">No invoices yet. Upload an invoice to begin.</p>}</div>
    </section>
  </div>
}

function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const processingLock = useRef(false)
  const previewRef = useRef<string|null>(null)
  const [file,setFile] = useState<File|null>(null)
  const [previewUrl,setPreviewUrl] = useState<string|null>(null)
  const [result,setResult] = useState<any>(null)
  const [progress,setProgress] = useState<any>(null)
  const [error,setError] = useState('')
  const qc = useQueryClient()
  function selectFile(next: File|null) {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = next && next.type.startsWith('image/') ? URL.createObjectURL(next) : null
    setPreviewUrl(previewRef.current)
    setFile(next)
  }
  useEffect(() => () => {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
  }, [])
  const upload = useMutation({mutationFn: async()=>{if(!file) throw new Error('Select an invoice first.'); const form=new FormData();form.append('file',file);return api<any>('/api/invoices/upload',{method:'POST',body:form})}})
  const analyze = useMutation({mutationFn:async(uploadId:string)=>{
    const queued=await api<any>(`/api/invoices/${encodeURIComponent(uploadId)}/analyze`,{method:'POST'})
    let job:any
    do {
      job=await api<any>(`/api/processing/${encodeURIComponent(queued.job_id)}`)
      setProgress(job)
      if(job.status==='failed') throw new Error(job.error||'Invoice processing failed.')
      if(job.status!=='complete') await new Promise(resolve=>window.setTimeout(resolve,700))
    } while(job.status!=='complete')
    return job.result
  },onSuccess:()=>qc.invalidateQueries()})
  async function processFile(){if(!file||processingLock.current)return;processingLock.current=true;const started=window.performance.now();setError('');setResult(null);setProgress(null);try{const uploadStarted=window.performance.now();const uploaded=await upload.mutateAsync();const clientUploadSeconds=(window.performance.now()-uploadStarted)/1000;const processed=await analyze.mutateAsync(uploaded.upload_id);setResult({...processed,performance:{...processed.performance,client_upload_seconds:Number(clientUploadSeconds.toFixed(4)),client_end_to_end_seconds:Number(((window.performance.now()-started)/1000).toFixed(4))}})}catch(err){setError(err instanceof Error?err.message:'Invoice processing failed for an unknown reason.')}finally{processingLock.current=false}}
  return <div className="space-y-6">
    <PageHeader title="Upload invoice" subtitle="Automatically extract, validate and save invoice data"/>
    <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <div onDragOver={(e)=>e.preventDefault()} onDrop={(e)=>{e.preventDefault();selectFile(e.dataTransfer.files[0]||null)}} className="grid min-h-64 place-items-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-8 text-center">
        {file ? <div>{previewUrl&&<img src={previewUrl} alt="Selected invoice" className="mx-auto mb-4 max-h-72 rounded-lg"/>}<p className="font-semibold">{file.name}</p><p className="text-sm text-slate-500">{(file.size/1024).toFixed(1)} KB</p><button className="mt-4 text-sm text-red-600" onClick={()=>selectFile(null)}>Remove file</button></div>
        : <div><UploadCloud className="mx-auto text-blue-600" size={42}/><p className="mt-3 font-semibold">Drop an invoice here</p><p className="text-sm text-slate-500">JPG, PNG or PDF · Maximum 20 MB</p><button className="mt-5 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white" onClick={()=>inputRef.current?.click()}>Browse files</button></div>}
        <input ref={inputRef} type="file" accept=".jpg,.jpeg,.png,.pdf" className="hidden" onChange={(e)=>{selectFile(e.target.files?.[0]||null);e.currentTarget.value=''}} />
      </div>
      {error&&<p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button disabled={!file||upload.isPending||analyze.isPending} onClick={processFile} className="mt-5 w-full rounded-lg bg-slate-950 px-5 py-3 font-semibold text-white disabled:opacity-50">{upload.isPending||analyze.isPending?'Processing invoice…':'Process Invoice Automatically'}</button>
    </section>
    {upload.isPending&&<section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Processing stages</h2><p className="mt-2 text-sm text-blue-700">Uploading the selected file…</p></section>}
    {analyze.isPending&&<section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Processing stages</h2><p className="mt-1 text-sm text-slate-500">Current stage: {progress?.current_stage||'Queued'}{progress?.queue_position?` · Queue position ${progress.queue_position}`:''}</p><div className="mt-4 space-y-2">{Object.entries(progress?.stages||{}).map(([stage,value]:[string,any])=><div key={stage} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><span>{stage}{value.detail?` · ${value.detail}`:''}</span><span className={value.status==='Complete'?'font-medium text-emerald-700':'text-blue-700'}>{value.status}</span></div>)}</div></section>}
    {result&&<AnalysisResults result={result}/>}
  </div>
}

function AnalysisResults({result}:{result:any}) {
  const metrics=result.performance||{}
  const metricLabels:Record<string,string>={upload_seconds:'Upload storage (server)',client_upload_seconds:'Upload (browser)',file_validation_seconds:'File validation',pdf_conversion_seconds:'PDF conversion',preprocessing_seconds:'OpenCV preprocessing',ocr_seconds:'Tesseract OCR',deterministic_extraction_seconds:'Python field and line-item extraction',mistral_inference_seconds:'Optional AI enrichment',optional_ai_enrichment_seconds:'Optional AI enrichment',ollama_total_seconds:'Ollama total',ollama_load_seconds:'Ollama model load',ollama_prompt_eval_seconds:'Ollama prompt evaluation',ollama_generation_seconds:'Ollama generation',ollama_prompt_tokens:'Ollama prompt tokens',ollama_generated_tokens:'Ollama generated tokens',ollama_tokens_per_second:'Ollama generation speed',pydantic_validation_seconds:'Pydantic validation',financial_validation_seconds:'Financial validation',duplicate_detection_seconds:'File duplicate check',invoice_number_duplicate_check_seconds:'Invoice-number duplicate check',database_insertion_seconds:'Database insertion',database_save_seconds:'Database save',total_processing_seconds:'Processing total',total_end_to_end_seconds:'End-to-end (server)',client_end_to_end_seconds:'End-to-end (browser)'}
  return <section className="grid gap-6 rounded-2xl border border-slate-200 bg-white p-6 lg:grid-cols-2">
    <div><h2 className="mb-4 text-lg font-bold">OCR text</h2><pre className="max-h-96 overflow-auto rounded-lg bg-slate-950 p-4 text-xs whitespace-pre-wrap text-slate-200">{result.ocr?.text||'No OCR text was needed for this duplicate.'}</pre></div>
    <div>
      {result.ocr?.document?.warning&&<p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{result.ocr.document.warning}</p>}
      <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">Automatic processing result</h2><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{result.processing_status||result.validation?.status}</span></div>
      {result.duplicate?<p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Duplicate invoice detected. No new record was added. Existing invoice: {result.invoice_id??'not found'}.</p>:<p className={`mb-4 rounded-lg p-3 text-sm ${result.processing_status==='Processed'?'bg-emerald-50 text-emerald-800':'bg-amber-50 text-amber-800'}`}>{result.processing_status==='Processed'?'Invoice validated and saved automatically.':`Saved to history as ${result.processing_status||'Needs Attention'}; it is excluded from financial totals.`} {result.invoice_id?`Invoice #${result.invoice_id}.`:''}</p>}
      {result.enrichment_status&&result.enrichment_status!=='not_needed'&&<p className="mb-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">Optional AI enrichment: {result.enrichment_status}. The invoice was saved before enrichment started.</p>}
      {result.invoice&&<dl className="grid gap-3 sm:grid-cols-2">{[['Invoice number',result.invoice.invoice_number],['Invoice date',result.invoice.invoice_date],['Vendor',result.invoice.vendor_name],['Vendor GSTIN',result.invoice.vendor_gstin],['Customer',result.invoice.customer_name],['Customer GSTIN',result.invoice.customer_gstin],['Subtotal',result.invoice.subtotal],['Tax',result.invoice.total_tax],['Grand total',result.invoice.grand_total]].map(([label,value])=><div key={label} className="rounded-lg bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium">{value??'Not extracted'}</dd></div>)}</dl>}
      {result.evidence&&<div className="mt-5"><h3 className="font-semibold">Extraction evidence</h3><div className="mt-2 space-y-2">{Object.entries(result.evidence).map(([field,value]:[string,any])=>Array.isArray(value)?<div key={field} className="space-y-2">{value.map((item:any)=><article key={item.item} className="rounded-lg border border-slate-200 p-3"><p className="text-xs font-semibold">Line item {item.item}</p><div className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(item.fields).map(([name,evidence]:[string,any])=><p key={name} className="break-words text-xs"><span className="font-medium capitalize">{name.replaceAll('_',' ')} · {evidence.source}</span><span className="block text-slate-500">{evidence.line||'No supporting OCR text found'}</span></p>)}</div></article>)}</div>:<div key={field} className="rounded-lg border border-slate-200 px-3 py-2 text-sm"><div className="flex items-center justify-between gap-3"><span className="font-medium capitalize">{field.replaceAll('_',' ')}</span><span className="text-[10px] uppercase tracking-wide text-slate-400">{value.source}</span></div><span className="mt-1 block break-words text-xs text-slate-500">{value.line||'No supporting OCR text found'}</span></div>)}</div></div>}
      {[...(result.validation?.errors||[]),...(result.validation?.warnings||[]),...(result.validation?.missing_fields||[]).map((field:string)=>`Missing required field: ${field}`)].map((message:string)=><p key={message} className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{message}</p>)}
      <div className="mt-5"><h3 className="font-semibold">Measured performance</h3><dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(metricLabels).filter(([key])=>metrics[key]!==undefined).map(([key,label])=><div key={key} className="flex justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm"><dt>{label}</dt><dd className="font-mono">{key.endsWith('_tokens')?`${Number(metrics[key]).toLocaleString()} tokens`:key.endsWith('_per_second')?`${Number(metrics[key]).toFixed(2)} tokens/s`:`${Number(metrics[key]).toFixed(4)} s`}</dd></div>)}</dl><p className="mt-3 text-sm text-slate-600">Slowest measured stage: <span className="font-semibold">{result.slowest_stage}</span></p></div>
    </div>
  </section>
}

function HistoryPage() {
  const [search,setSearch]=useState('')
  const [status,setStatus]=useState('')
  const [page,setPage]=useState(1)
  const [selectedId,setSelectedId]=useState<number|null>(null)
  const [editing,setEditing]=useState(false)
  const [editData,setEditData]=useState<Record<string,string>>({})
  const pageSize=10
  const qc=useQueryClient()
  const querySuffix=new URLSearchParams()
  if(search)querySuffix.set('search',search)
  if(status)querySuffix.set('status',status)
  const queryString=querySuffix.toString()
  const {data=[],isLoading,error}=useQuery({queryKey:['invoices',search,status],queryFn:()=>api<Invoice[]>(`/api/invoices${queryString?`?${queryString}`:''}`)})
  const details=useQuery({queryKey:['invoice',selectedId],queryFn:()=>api<any>(`/api/invoices/${selectedId}`),enabled:selectedId!==null})
  const correction=useMutation({mutationFn:()=>api<any>(`/api/invoices/${selectedId}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({invoice_number:editData.invoice_number||null,invoice_date:editData.invoice_date||null,vendor_name:editData.vendor_name||null,subtotal:editData.subtotal===''?null:Number(editData.subtotal),total_tax:editData.total_tax===''?null:Number(editData.total_tax),grand_total:editData.grand_total===''?null:Number(editData.grand_total)})}),onSuccess:()=>{setEditing(false);void qc.invalidateQueries({queryKey:['invoices']});void qc.invalidateQueries({queryKey:['invoice',selectedId]})}})
  const deletion=useMutation({mutationFn:()=>api(`/api/invoices/${selectedId}`,{method:'DELETE'}),onSuccess:()=>{setSelectedId(null);setEditing(false);void qc.invalidateQueries()}})
  if(isLoading)return <PageLoading/>
  if(error)return <PageError error={error as Error}/>
  const ordered=[...data].sort((a,b)=>(b.invoice_date||'').localeCompare(a.invoice_date||''))
  const pageCount=Math.max(1,Math.ceil(ordered.length/pageSize))
  const visible=ordered.slice((page-1)*pageSize,page*pageSize)
  function beginEdit() {
    const invoice=details.data?.invoice
    if(!invoice)return
    setEditData(Object.fromEntries(['invoice_number','invoice_date','vendor_name','subtotal','total_tax','grand_total'].map(key=>[key,invoice[key]??''])))
    setEditing(true)
    correction.reset()
  }
  function removeInvoice() {
    if(window.confirm('Permanently delete this invoice and its stored upload when no other record uses it?')) deletion.mutate()
  }
  return <div className="space-y-6">
    <PageHeader title="Invoice register" subtitle="Search, review, correct, and export your invoice records"/>
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Search invoices</span><input value={search} onChange={event=>{setSearch(event.target.value);setPage(1)}} placeholder="Search vendor, invoice number, or file" className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm focus:bg-white"/></label>
        <label><span className="sr-only">Filter by validation status</span><select value={status} onChange={event=>{setStatus(event.target.value);setPage(1)}} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm sm:w-48"><option value="">All statuses</option><option value="Verified">Verified</option><option value="Needs Attention">Needs Attention</option><option value="Validation Failed">Validation Failed</option></select></label>
        <button onClick={()=>downloadReport().catch(error=>window.alert(error.message))} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">Export CSV</button>
      </div>
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-100"><table className="w-full min-w-[880px] text-left text-sm"><thead className="bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500"><tr>{['Invoice','Vendor','Date','Subtotal','Tax','Grand total','Status','Details'].map(label=><th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{visible.map(row=><tr key={row.id} className="border-t border-slate-100 hover:bg-slate-50/70"><td className="px-4 py-3 font-semibold">{row.invoice_number||`Invoice ${row.id}`}</td><td className="px-4 py-3">{row.vendor_name||'Unknown'}</td><td className="px-4 py-3 text-slate-500">{row.invoice_date||'—'}</td><td className="px-4 py-3">₹{Number((row as any).subtotal||0).toLocaleString('en-IN')}</td><td className="px-4 py-3">₹{Number(row.total_tax||0).toLocaleString('en-IN')}</td><td className="px-4 py-3 font-medium">₹{Number(row.grand_total||0).toLocaleString('en-IN')}</td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs ${(row.validation_status||'')==='Verified'?'bg-emerald-50 text-emerald-700':'bg-amber-50 text-amber-700'}`}>{row.validation_status||'Needs Attention'}</span></td><td className="px-4 py-3"><button className="font-semibold text-indigo-700 hover:text-indigo-900" onClick={()=>{setSelectedId(row.id);setEditing(false)}}>Open</button></td></tr>)}</tbody></table>
        {!visible.length&&<p className="p-8 text-center text-sm text-slate-500">No invoices match these filters.</p>}</div>
      <div className="flex items-center justify-between pt-4 text-sm text-slate-500"><span>{ordered.length} record(s) · Page {page} of {pageCount}</span><div className="flex gap-2"><button aria-label="Previous page" disabled={page<=1} onClick={()=>setPage(value=>Math.max(1,value-1))} className="rounded-lg border border-slate-200 p-2 disabled:opacity-40"><ChevronLeft size={16}/></button><button aria-label="Next page" disabled={page>=pageCount} onClick={()=>setPage(value=>Math.min(pageCount,value+1))} className="rounded-lg border border-slate-200 p-2 disabled:opacity-40"><ChevronRightIcon size={16}/></button></div></div>
    </section>
    {selectedId!==null&&<section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">Invoice detail</p><h2 className="mt-1 text-lg font-bold">{details.data?.invoice?.invoice_number||`Invoice ${selectedId}`}</h2></div><div className="flex items-center gap-2"><button onClick={beginEdit} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium hover:bg-slate-50"><Pencil size={14}/>Correct fields</button><button onClick={removeInvoice} disabled={deletion.isPending} className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50">Delete</button><button onClick={()=>setSelectedId(null)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Close details"><X size={18}/></button></div></div>
      {details.isLoading?<p className="mt-4 text-sm text-slate-500">Loading details…</p>:details.error?<PageError error={details.error as Error}/>:details.data&&<div className="mt-5">
        {editing?<form onSubmit={event=>{event.preventDefault();correction.mutate()}} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {['invoice_number','invoice_date','vendor_name','subtotal','total_tax','grand_total'].map(field=><label key={field} className="text-xs font-medium capitalize text-slate-500">{field.replaceAll('_',' ')}<input type={field.includes('subtotal')||field.includes('tax')||field.includes('total')?'number':'text'} step="0.01" value={editData[field]||''} onChange={event=>setEditData(data=>({...data,[field]:event.target.value}))} className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800"/></label>)}
          <div className="flex items-end gap-2"><button disabled={correction.isPending} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Check size={15}/>Save corrections</button><button type="button" onClick={()=>setEditing(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Cancel</button></div>
        </form>:<dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[['Invoice date',details.data.invoice.invoice_date],['Vendor',details.data.invoice.vendor_name],['Subtotal',details.data.invoice.subtotal],['Tax',details.data.invoice.total_tax],['Grand total',details.data.invoice.grand_total],['Validation',details.data.invoice.validation_status],['Processing',details.data.invoice.processing_status]].map(([label,value])=><div key={label} className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-semibold">{value??'Not available'}</dd></div>)}</dl>}
        {correction.error&&<p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{(correction.error as Error).message}</p>}
        {deletion.error&&<p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{(deletion.error as Error).message}</p>}
        <h3 className="mt-6 font-semibold">Line items</h3><div className="mt-2 space-y-2">{(details.data.items||[]).map((item:any,index:number)=><div key={item.id||index} className="flex justify-between gap-4 rounded-xl border border-slate-100 px-3 py-3 text-sm"><span>{item.description||'Unspecified item'} <span className="text-slate-500">· {item.category||'Other'}{item.discount_percent?` · ${item.discount_percent}% discount`:''}{item.discount?` · ₹${Number(item.discount).toLocaleString('en-IN')} discount`:''}</span>{item.evidence?.fields?.description?.line&&<span className="mt-1 block text-xs text-slate-500">OCR: {item.evidence.fields.description.line} · confidence {Math.round((item.confidence||0)*100)}%</span>}</span><span className="font-medium">₹{Number(item.amount||0).toLocaleString('en-IN')}</span></div>)}{!details.data.items?.length&&<p className="text-sm text-slate-500">No line items were extracted.</p>}</div>
        <section className="mt-6 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Optional AI enrichment</h3><p className="mt-1 text-sm text-slate-600">Status: {details.data.invoice.enrichment_status||'not available'}</p>{details.data.invoice.enrichment_error&&<p className="mt-2 text-sm text-amber-800">{details.data.invoice.enrichment_error}</p>}{Object.keys(details.data.invoice.enrichment||{}).length>0&&<pre className="mt-3 overflow-auto rounded-lg bg-slate-50 p-3 text-xs whitespace-pre-wrap">{JSON.stringify(details.data.invoice.enrichment,null,2)}</pre>}</section>
        <details className="mt-4 rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold">OCR text and field evidence</summary><pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-slate-950 p-3 text-xs whitespace-pre-wrap text-slate-100">{details.data.invoice.ocr_text||'No OCR text was retained for this legacy record.'}</pre><div className="mt-3 space-y-2">{Object.entries(details.data.invoice.field_evidence||{}).filter(([field])=>field!=='items').map(([field,evidence]:[string,any])=><p key={field} className="rounded-lg bg-slate-50 p-2 text-xs"><span className="font-semibold capitalize">{field.replaceAll('_',' ')} · {Math.round((details.data.invoice.field_confidence?.[field]||0)*100)}%</span><span className="block text-slate-500">{evidence.line||'No direct OCR evidence'}</span></p>)}</div></details>
      </div>}
    </section>}
  </div>
}

function AnalyticsPage() {
  const {data,isLoading,error}=useQuery({queryKey:['overview'],queryFn:()=>api<any>('/api/analytics/overview')})
  if(isLoading)return <PageLoading/>
  if(error)return <PageError error={error as Error}/>
  return <div className="space-y-6"><PageHeader title="Expense analytics" subtitle="Validated invoice spending and tax analysis"/><div className="grid gap-6 lg:grid-cols-2">
    <ChartCard title="Vendor expenditure"><ResponsiveContainer width="100%" height={320}><BarChart data={data.vendors} layout="vertical"><CartesianGrid strokeDasharray="3 3"/><XAxis type="number"/><YAxis type="category" dataKey="vendor" width={110}/><Tooltip/><Bar dataKey="amount" fill="#2563eb"/></BarChart></ResponsiveContainer></ChartCard>
    <ChartCard title="Expense categories"><ResponsiveContainer width="100%" height={320}><PieChart><Pie data={data.categories} dataKey="amount" nameKey="category" outerRadius={110} fill="#2563eb"/><Tooltip/><Legend/></PieChart></ResponsiveContainer></ChartCard>
  </div></div>
}

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  rows?: Record<string, unknown>[]
  details?: Record<string, unknown>[]
  context?: Record<string, unknown>
}

function assistantCell(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number' && /(amount|total|tax|average|grand_total|subtotal)/i.test(key)) {
    return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  }
  return String(value)
}

function AssistantPage() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [failedQuestion, setFailedQuestion] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const suggestions = [
    'What is my total expenditure this month?',
    'Which vendor has the highest payment?',
    'Show my top five expense categories',
    'How much GST have I paid?',
  ]
  const mutation = useMutation({
    mutationFn: ({prompt, previous}: {prompt: string; previous: ChatMessage[]}) => api<any>(
      '/api/assistant/query',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: prompt, history: previous}),
      },
    ),
    onSuccess: result => {
      setHistory(items => [...items, {
        role: 'assistant',
        content: result.answer || 'No answer was returned.',
        rows: result.supporting_invoices || result.rows || [],
        details: result.calculation?.line_items || [],
        context: result.context || {},
      }])
      setFailedQuestion('')
      setQuestion('')
    },
    onError: (_error, variables) => setFailedQuestion(variables.prompt),
  })
  useEffect(() => {
    bottomRef.current?.scrollIntoView({behavior: 'smooth', block: 'end'})
  }, [history, mutation.isPending])
  function ask(prompt: string, retry = false) {
    const text = prompt.trim()
    if (!text || mutation.isPending) return
    const previous = retry ? history.slice(0, -1) : history
    if (!retry) setHistory(items => [...items, {role: 'user', content: text}])
    mutation.mutate({prompt: text, previous})
  }
  function clearConversation() {
    setHistory([])
    setFailedQuestion('')
    mutation.reset()
  }
  return <div className="space-y-6">
    <PageHeader title="AI expense assistant" subtitle="Ask questions about your invoice records. Financial answers are calculated directly from verified SQLite data."/>
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-50 text-indigo-700"><Bot size={21}/></span><div><h2 className="font-semibold text-slate-900">FinSight assistant</h2><p className="text-xs text-slate-500">Private to your local invoice database</p></div></div>
        <button onClick={clearConversation} disabled={!history.length&&!mutation.error} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 disabled:opacity-40" aria-label="Clear conversation"><Trash2 size={15}/> <span className="hidden sm:inline">Clear chat</span></button>
      </header>
      <div className="min-h-[320px] max-h-[60vh] space-y-5 overflow-y-auto bg-[#fafbfe] px-4 py-5 sm:px-6">
        {!history.length&&<div className="mx-auto max-w-xl py-8 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-indigo-100 text-indigo-700"><Bot size={27}/></div><h3 className="mt-4 text-lg font-semibold">Your finances, in plain language</h3><p className="mt-1 text-sm text-slate-500">Ask about verified spending, vendors, taxes, and invoice records.</p><div className="mt-6 grid gap-2 text-left sm:grid-cols-2">{suggestions.map(item=><button key={item} onClick={()=>ask(item)} className="rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700 transition hover:border-indigo-300 hover:bg-indigo-50">{item}</button>)}</div></div>}
        {history.map((message,index)=><article key={`${index}-${message.role}`} className={`flex gap-3 ${message.role==='user'?'justify-end':''}`}>
          {message.role==='assistant'&&<span className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-indigo-100 text-indigo-700"><Bot size={17}/></span>}
          <div className={`max-w-[92%] rounded-2xl px-4 py-3 sm:max-w-[82%] ${message.role==='user'?'rounded-br-md bg-[#202b46] text-white':'rounded-bl-md border border-slate-200 bg-white text-slate-800 shadow-sm'}`}>
            <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
            {!!message.rows?.length&&<div className="mt-3 max-w-full overflow-x-auto rounded-lg border border-slate-200"><table className="min-w-full text-left text-xs"><thead className="bg-slate-50 text-slate-500"><tr>{Object.keys(message.rows[0]).map(key=><th key={key} className="whitespace-nowrap px-3 py-2 font-semibold">{key.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{message.rows.slice(0,20).map((row,rowIndex)=><tr key={rowIndex} className="border-t border-slate-100">{Object.entries(message.rows?.[0]||{}).map(([key])=><td key={key} className="whitespace-nowrap px-3 py-2">{assistantCell(key,row[key])}</td>)}</tr>)}</tbody></table></div>}
            {!!message.details?.length&&<div className="mt-3 max-w-full overflow-x-auto rounded-lg border border-slate-200"><p className="bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">Stored line items</p><table className="min-w-full text-left text-xs"><thead className="bg-slate-50 text-slate-500"><tr>{Object.keys(message.details[0]).map(key=><th key={key} className="whitespace-nowrap px-3 py-2 font-semibold">{key.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{message.details.slice(0,20).map((row,rowIndex)=><tr key={rowIndex} className="border-t border-slate-100">{Object.entries(message.details?.[0]||{}).map(([key])=><td key={key} className="whitespace-nowrap px-3 py-2">{assistantCell(key,row[key])}</td>)}</tr>)}</tbody></table></div>}
          </div>
          {message.role==='user'&&<span className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-200 text-slate-600"><FileText size={16}/></span>}
        </article>)}
        {mutation.isPending&&<div className="flex items-center gap-3"><span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-100 text-indigo-700"><Bot size={17}/></span><div className="flex items-center gap-1 rounded-2xl border border-slate-200 bg-white px-4 py-3" aria-label="Assistant is thinking"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500"/><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500 [animation-delay:150ms]"/><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500 [animation-delay:300ms]"/><span className="ml-2 text-xs text-slate-500">Checking invoice records…</span></div></div>}
        <div ref={bottomRef}/>
      </div>
      {mutation.error&&<div className="mx-5 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><span>{(mutation.error as Error).message}</span><button onClick={()=>ask(failedQuestion||history.at(-1)?.content||'',true)} disabled={!failedQuestion&&!history.length} className="font-semibold underline">Retry</button></div>}
      <form className="flex items-end gap-3 border-t border-slate-100 bg-white p-4 sm:p-5" onSubmit={event=>{event.preventDefault();ask(question)}}>
        <label className="sr-only" htmlFor="assistant-question">Ask about your expenses</label>
        <textarea id="assistant-question" rows={1} value={question} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();ask(question)}}} placeholder="Ask a question about your invoices…" className="max-h-28 min-h-11 flex-1 resize-y rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-indigo-400 focus:bg-white" />
        <button type="submit" aria-label="Send message" disabled={!question.trim()||mutation.isPending} className="flex h-11 items-center gap-2 rounded-xl bg-indigo-600 px-4 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"><Send size={16}/><span className="hidden sm:inline">Send</span></button>
      </form>
      <p className="px-5 pb-4 text-[11px] text-slate-400">Financial totals only include invoices marked Verified. Press Enter to send, Shift+Enter for a new line.</p>
    </section>
  </div>
}

function SettingsPage() {
  const {data,isLoading,error}=useQuery({queryKey:['status'],queryFn:()=>api<any>('/api/system/status')})
  if(isLoading)return <PageLoading/>
  if(error)return <PageError error={error as Error}/>
  const ollama=data.ollama||{}
  const cards=[
    ['Backend',data.backend],['Database',data.database],['OCR',data.ocr],
    ['Tesseract',data.tesseract_version||'Unavailable'],
    ['Ollama',ollama.reachable?`Connected${ollama.version?` · v${ollama.version}`:''}`:'Unavailable'],
    ['Selected model',ollama.selected_model||'Not configured'],
    ['Model availability',ollama.selected_model_available?'Installed':'Not installed'],
    ['Loaded model processor',ollama.processor_usage||'Unknown'],
    ['GPU VRAM in use',ollama.vram_bytes?`${(ollama.vram_bytes/1024/1024/1024).toFixed(2)} GB`:'0 GB / not loaded'],
    ['CPU',ollama.cpu_name||'Not reported'],
    ['CPU threads',ollama.cpu_threads||'Unknown'],
    ['System RAM',ollama.ram_total_bytes?`${(ollama.ram_total_bytes/1024/1024/1024).toFixed(1)} GB total · ${(ollama.ram_available_bytes/1024/1024/1024).toFixed(1)} GB available`:'Not reported'],
    ['Context window',ollama.context_window||'Unknown'],['LayoutLMv3',data.layoutlm],
  ]
  return <div className="space-y-6"><PageHeader title="System settings" subtitle="Local services, model readiness, and detected hardware"/>
    {!ollama.reachable&&<p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Ollama is unavailable. Invoice OCR, deterministic extraction, validation, and saving continue without it; optional enrichment is paused.{ollama.error?` ${ollama.error}`:''}</p>}
    {ollama.reachable&&!ollama.selected_model_available&&<p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">The configured model is optional. Install it with <code>ollama pull {ollama.selected_model}</code> to enable background enrichment. No model is downloaded automatically.</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{cards.map(([label,value])=><article key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-2 break-words text-sm font-semibold text-slate-900">{value||'Unknown'}</p></article>)}</div>
  </div>
}
