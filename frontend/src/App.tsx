import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { HashRouter, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Bot, ChevronRight, FileText, LayoutDashboard, Settings, UploadCloud, Wifi, WifiOff } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, downloadReport, setPairingToken } from './services/api'

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
    ['/', 'Overview', LayoutDashboard],
    ['/upload', 'Upload invoice', UploadCloud],
    ['/history', 'Invoice history', FileText],
    ['/analytics', 'Analytics', BarChart3],
    ['/assistant', 'AI assistant', Bot],
    ['/settings', 'Settings', Settings],
  ] as const
  async function connect() {
    const token = window.prompt('Enter the local pairing token printed by start_backend.ps1.')
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
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <aside className="fixed left-0 top-0 z-20 hidden h-screen w-64 bg-slate-950 px-5 py-6 md:block">
        <button className="mb-8 flex items-center gap-3" onClick={() => navigate('/')}>
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-500 text-lg font-bold text-white">I</span>
          <span className="text-left"><span className="block font-semibold text-white">Invoice Intelligence</span><span className="block text-xs text-slate-400">Financial workspace</span></span>
        </button>
        <nav className="space-y-1">
          {nav.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} className={({isActive}) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-900 hover:text-white'}`}>
              <Icon size={18} /> {label}
            </NavLink>
          ))}
        </nav>
        <button onClick={connect} className="absolute bottom-6 left-5 right-5 flex items-center justify-between rounded-lg border border-slate-800 px-3 py-2 text-sm text-slate-300">
          <span className="flex items-center gap-2">{connected ? <Wifi size={16} className="text-emerald-400"/> : <WifiOff size={16}/>} {connected === true ? 'Backend connected' : 'Connect backend'}</span>
          <ChevronRight size={16}/>
        </button>
      </aside>
      <main className="md:ml-64"><div className="mx-auto max-w-[1400px] p-4 md:p-8">
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
  return <header><h1 className="text-3xl font-bold tracking-tight">{title}</h1><p className="mt-1 text-slate-500">{subtitle}</p></header>
}
function PageLoading() { return <div className="rounded-xl border bg-white p-8 text-center text-slate-500">Loading…</div> }
function PageError({error}:{error:Error}) { return <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">Unable to load the local backend. {error.message}</div> }
function ChartCard({title, children}:{title:string;children:ReactNode}) { return <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="mb-4 font-semibold">{title}</h2>{children}</article> }

function Overview() {
  const {data, isLoading, error} = useQuery({queryKey:['overview'], queryFn:()=>api<any>('/api/analytics/overview')})
  if (isLoading) return <PageLoading/>
  if (error) return <PageError error={error as Error}/>
  const s = data.summary || {}
  const cards = [['Verified expenses',`₹${Number(s.total_expenses||0).toLocaleString('en-IN')}`],['Verified invoices',s.total_invoices||0],['Tax paid',`₹${Number(s.total_tax||0).toLocaleString('en-IN')}`],['Average invoice',`₹${Number(s.average_invoice||0).toLocaleString('en-IN')}`],['Needs attention',s.needs_attention||0]]
  return <div className="space-y-6">
    <PageHeader title="Overview" subtitle="Validated financial activity and automatic processing"/>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{cards.map(([label,value])=><article key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm text-slate-500">{label}</p><p className="mt-2 text-2xl font-bold">{value}</p></article>)}</div>
    <div className="grid gap-6 lg:grid-cols-2">
      <ChartCard title="Monthly spending"><ResponsiveContainer width="100%" height={280}><BarChart data={data.monthly}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="month"/><YAxis/><Tooltip/><Bar dataKey="amount" fill="#2563eb" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer></ChartCard>
      <ChartCard title="Category distribution"><ResponsiveContainer width="100%" height={280}><PieChart><Pie data={data.categories} dataKey="amount" nameKey="category" innerRadius={65} outerRadius={95} fill="#2563eb"/><Tooltip/><Legend/></PieChart></ResponsiveContainer></ChartCard>
    </div>
  </div>
}

function UploadPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const processingLock = useRef(false)
  const [file,setFile] = useState<File|null>(null)
  const [preview,setPreview] = useState<{file:File;url:string}|null>(null)
  const [result,setResult] = useState<any>(null)
  const [progress,setProgress] = useState<any>(null)
  const [error,setError] = useState('')
  const qc = useQueryClient()
  useEffect(() => {
    if (!file || !file.type.startsWith('image/')) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview({file, url})
    return () => URL.revokeObjectURL(url)
  }, [file])
  const previewUrl = preview?.file === file ? preview.url : null
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
      <div onDragOver={(e)=>e.preventDefault()} onDrop={(e)=>{e.preventDefault();setFile(e.dataTransfer.files[0]||null)}} className="grid min-h-64 place-items-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-8 text-center">
        {file ? <div>{previewUrl&&<img src={previewUrl} alt="Selected invoice" className="mx-auto mb-4 max-h-72 rounded-lg"/>}<p className="font-semibold">{file.name}</p><p className="text-sm text-slate-500">{(file.size/1024).toFixed(1)} KB</p><button className="mt-4 text-sm text-red-600" onClick={()=>setFile(null)}>Remove file</button></div>
        : <div><UploadCloud className="mx-auto text-blue-600" size={42}/><p className="mt-3 font-semibold">Drop an invoice here</p><p className="text-sm text-slate-500">JPG, PNG or PDF · Maximum 20 MB</p><button className="mt-5 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white" onClick={()=>inputRef.current?.click()}>Browse files</button></div>}
        <input ref={inputRef} type="file" accept=".jpg,.jpeg,.png,.pdf" className="hidden" onChange={(e)=>{setFile(e.target.files?.[0]||null);e.currentTarget.value=''}} />
      </div>
      {error&&<p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button disabled={!file||upload.isPending||analyze.isPending} onClick={processFile} className="mt-5 w-full rounded-lg bg-slate-950 px-5 py-3 font-semibold text-white disabled:opacity-50">{upload.isPending||analyze.isPending?'Processing invoice…':'Process Invoice Automatically'}</button>
    </section>
    {upload.isPending&&<section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Processing stages</h2><p className="mt-2 text-sm text-blue-700">Uploading the selected file…</p></section>}
    {analyze.isPending&&<section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Processing stages</h2><p className="mt-1 text-sm text-slate-500">Current stage: {progress?.current_stage||'Queued'}</p><div className="mt-4 space-y-2">{Object.entries(progress?.stages||{}).map(([stage,value]:[string,any])=><div key={stage} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><span>{stage}{value.detail?` · ${value.detail}`:''}</span><span className={value.status==='Complete'?'font-medium text-emerald-700':'text-blue-700'}>{value.status}</span></div>)}</div></section>}
    {result&&<AnalysisResults result={result}/>}
  </div>
}

function AnalysisResults({result}:{result:any}) {
  const metrics=result.performance||{}
  const metricLabels:Record<string,string>={upload_seconds:'Upload storage (server)',client_upload_seconds:'Upload (browser)',file_validation_seconds:'File validation',pdf_conversion_seconds:'PDF conversion',preprocessing_seconds:'OpenCV preprocessing',ocr_seconds:'Tesseract OCR',mistral_inference_seconds:'Mistral inference',ollama_total_seconds:'Ollama total',ollama_load_seconds:'Ollama model load',ollama_prompt_eval_seconds:'Ollama prompt evaluation',ollama_generation_seconds:'Ollama generation',ollama_prompt_tokens:'Ollama prompt tokens',ollama_generated_tokens:'Ollama generated tokens',ollama_tokens_per_second:'Ollama generation speed',pydantic_validation_seconds:'Pydantic validation',financial_validation_seconds:'Financial validation',duplicate_detection_seconds:'File duplicate check',invoice_number_duplicate_check_seconds:'Invoice-number duplicate check',database_insertion_seconds:'Database insertion',total_processing_seconds:'Processing total',total_end_to_end_seconds:'End-to-end (server)',client_end_to_end_seconds:'End-to-end (browser)'}
  return <section className="grid gap-6 rounded-2xl border border-slate-200 bg-white p-6 lg:grid-cols-2">
    <div><h2 className="mb-4 text-lg font-bold">OCR text</h2><pre className="max-h-96 overflow-auto rounded-lg bg-slate-950 p-4 text-xs whitespace-pre-wrap text-slate-200">{result.ocr?.text||'No OCR text was needed for this duplicate.'}</pre></div>
    <div>
      {result.ocr?.document?.warning&&<p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{result.ocr.document.warning}</p>}
      <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-bold">Automatic processing result</h2><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{result.processing_status||result.validation?.status}</span></div>
      {result.duplicate?<p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Duplicate invoice detected. No new record was added. Existing invoice: {result.invoice_id??'not found'}.</p>:<p className={`mb-4 rounded-lg p-3 text-sm ${result.processing_status==='Processed'?'bg-emerald-50 text-emerald-800':'bg-amber-50 text-amber-800'}`}>{result.processing_status==='Processed'?'Invoice validated and saved automatically.':`Saved to history as ${result.processing_status||'Needs Attention'}; it is excluded from financial totals.`} {result.invoice_id?`Invoice #${result.invoice_id}.`:''}</p>}
      {result.invoice&&<dl className="grid gap-3 sm:grid-cols-2">{[['Invoice number',result.invoice.invoice_number],['Invoice date',result.invoice.invoice_date],['Vendor',result.invoice.vendor_name],['Vendor GSTIN',result.invoice.vendor_gstin],['Customer',result.invoice.customer_name],['Customer GSTIN',result.invoice.customer_gstin],['Subtotal',result.invoice.subtotal],['Tax',result.invoice.total_tax],['Grand total',result.invoice.grand_total]].map(([label,value])=><div key={label} className="rounded-lg bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium">{value??'Not extracted'}</dd></div>)}</dl>}
      {[...(result.validation?.errors||[]),...(result.validation?.warnings||[]),...(result.validation?.missing_fields||[]).map((field:string)=>`Missing required field: ${field}`)].map((message:string)=><p key={message} className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{message}</p>)}
      <div className="mt-5"><h3 className="font-semibold">Measured performance</h3><dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(metricLabels).filter(([key])=>metrics[key]!==undefined).map(([key,label])=><div key={key} className="flex justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm"><dt>{label}</dt><dd className="font-mono">{key.endsWith('_tokens')?`${Number(metrics[key]).toLocaleString()} tokens`:key.endsWith('_per_second')?`${Number(metrics[key]).toFixed(2)} tokens/s`:`${Number(metrics[key]).toFixed(4)} s`}</dd></div>)}</dl><p className="mt-3 text-sm text-slate-600">Slowest measured stage: <span className="font-semibold">{result.slowest_stage}</span></p></div>
    </div>
  </section>
}

function HistoryPage() {
  const [search,setSearch]=useState('')
  const [selectedId,setSelectedId]=useState<number|null>(null)
  const {data=[],isLoading,error}=useQuery({queryKey:['invoices',search],queryFn:()=>api<Invoice[]>(`/api/invoices${search?`?search=${encodeURIComponent(search)}`:''}`)})
  const details=useQuery({queryKey:['invoice',selectedId],queryFn:()=>api<any>(`/api/invoices/${selectedId}`),enabled:selectedId!==null})
  if(isLoading)return <PageLoading/>
  if(error)return <PageError error={error as Error}/>
  return <div className="space-y-6"><PageHeader title="Invoice history" subtitle="Search and inspect processed invoices"/>
    <input value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Search vendor or invoice number" className="w-full max-w-md rounded-lg border border-slate-300 bg-white px-4 py-2.5"/>
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-slate-500"><tr>{['Invoice','Vendor','Date','Amount','Status','Details'].map(x=><th key={x} className="px-4 py-3">{x}</th>)}</tr></thead><tbody>{data.map(row=><tr key={row.id} className="border-t border-slate-100"><td className="px-4 py-3 font-medium">{row.invoice_number||`Invoice ${row.id}`}</td><td className="px-4 py-3">{row.vendor_name||'Unknown'}</td><td className="px-4 py-3">{row.invoice_date||'—'}</td><td className="px-4 py-3">₹{Number(row.grand_total||0).toLocaleString('en-IN')}</td><td className="px-4 py-3"><span>{row.processing_status||'Needs Attention'}</span><span className="block text-xs text-slate-500">{row.validation_status||'Needs Attention'}</span></td><td className="px-4 py-3"><button className="text-blue-700" onClick={()=>setSelectedId(row.id)}>View</button></td></tr>)}</tbody></table>{!data.length&&<p className="p-8 text-center text-slate-500">No invoices found.</p>}</div>
    {selectedId!==null&&<section className="rounded-xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><h2 className="text-lg font-bold">Invoice details</h2><button className="text-sm text-slate-600" onClick={()=>setSelectedId(null)}>Close</button></div>{details.isLoading?<p className="mt-4 text-slate-500">Loading invoice details…</p>:details.error?<PageError error={details.error as Error}/>:details.data&&<><dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[['Invoice number',details.data.invoice.invoice_number],['Date',details.data.invoice.invoice_date],['Vendor',details.data.invoice.vendor_name],['Grand total',details.data.invoice.grand_total],['Validation',details.data.invoice.validation_status],['Processing',details.data.invoice.processing_status]].map(([label,value])=><div key={label} className="rounded-lg bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium">{value??'Not available'}</dd></div>)}</dl>        <h3 className="mt-5 font-semibold">Items</h3><div className="mt-2 space-y-2">{(details.data.items||[]).map((item:any,index:number)=><div key={item.id||index} className="flex justify-between gap-4 rounded-lg bg-slate-50 px-3 py-2 text-sm"><span>{item.description||'Unspecified item'} <span className="text-slate-500">· {item.category||'Other'}{item.discount_percent?` · ${item.discount_percent}% discount`:''}{item.discount?` · ₹${Number(item.discount).toLocaleString('en-IN')} discount`:''}</span></span><span>₹{Number(item.amount||0).toLocaleString('en-IN')}</span></div>)}{!details.data.items?.length&&<p className="text-sm text-slate-500">No line items were extracted.</p>}</div></>}</section>}
    <button onClick={()=>downloadReport().catch(error=>window.alert(error.message))} className="inline-block rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold">Export CSV</button>
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

function AssistantPage() {
  const [question,setQuestion]=useState('')
  const [history,setHistory]=useState<Array<{question:string;answer:any}>>([])
  const mutation=useMutation({mutationFn:()=>api<any>('/api/assistant/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})}),onSuccess:(answer)=>{setHistory(v=>[{question,answer},...v]);setQuestion('')}})
  return <div className="space-y-6"><PageHeader title="AI expense assistant" subtitle="Ask questions against expense records"/>
    <div className="rounded-xl border border-slate-200 bg-white p-5"><div className="flex gap-3"><input value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>e.key==='Enter'&&question&&mutation.mutate()} placeholder="What is my total GST expenditure?" className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5"/><button disabled={!question||mutation.isPending} onClick={()=>mutation.mutate()} className="rounded-lg bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">Ask</button></div>
      {mutation.error&&<p className="mt-3 text-sm text-red-600">{(mutation.error as Error).message}</p>}<div className="mt-5 space-y-4">{history.map((entry,index)=><article key={index} className="rounded-lg bg-slate-50 p-4"><p className="font-semibold">{entry.question}</p><pre className="mt-2 overflow-auto text-sm whitespace-pre-wrap">{JSON.stringify(entry.answer.rows,null,2)}</pre></article>)}</div>
    </div>
  </div>
}

function SettingsPage() {
  const {data,isLoading}=useQuery({queryKey:['status'],queryFn:()=>api<any>('/api/system/status')})
  return <div className="space-y-6"><PageHeader title="System settings" subtitle="Local backend and AI service availability"/>{isLoading?<PageLoading/>:<div className="grid gap-4 md:grid-cols-2">{[['Backend',data?.backend],['Database',data?.database],['OCR',data?.ocr],['Tesseract',data?.tesseract_version||'Unavailable'],['Ollama',data?.ollama?.reachable?'Connected':'Unavailable'],['Mistral',data?.ollama?.selected_model_available?'Available':'Unavailable'],['LayoutLMv3',data?.layoutlm]].map(([label,value])=><article key={label} className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-sm text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></article>)}</div>}</div>
}
