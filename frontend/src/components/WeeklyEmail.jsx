import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { emailAgentApi } from '../api/client'

const TONE_OPTIONS = [
  'Friendly & casual',
  'Professional update',
  'Story-driven',
  'Motivational',
]

function WeeklyEmail() {
  const queryClient = useQueryClient()
  const [step, setStep] = useState('brief') // brief | preview | sent
  const [brief, setBrief] = useState({
    what_happened: '',
    coming_up: '',
    tone: 'Friendly & casual',
    promo_mention: '',
    subject_idea: '',
  })
  const [draft, setDraft] = useState(null)
  const [editedSubject, setEditedSubject] = useState('')
  const [editedPreheader, setEditedPreheader] = useState('')
  const [editedHtml, setEditedHtml] = useState('')
  const [editedText, setEditedText] = useState('')
  const [previewWidth, setPreviewWidth] = useState('desktop')
  const [showConfirm, setShowConfirm] = useState(false)
  const [sendResult, setSendResult] = useState(null)
  const [error, setError] = useState(null)
  const iframeRef = useRef(null)

  // Audience count
  const { data: audienceData } = useQuery({
    queryKey: ['emailAgent', 'audience'],
    queryFn: async () => {
      const res = await emailAgentApi.getAudienceCount()
      return res.data
    },
    staleTime: 60000,
  })

  // Send history
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['emailAgent', 'history'],
    queryFn: async () => {
      const res = await emailAgentApi.getHistory()
      return res.data
    },
    staleTime: 30000,
  })

  // Generate mutation
  const generateMutation = useMutation({
    mutationFn: async (briefData) => {
      const res = await emailAgentApi.generate(briefData)
      return res.data
    },
    onSuccess: (data) => {
      if (data.success) {
        setDraft(data.draft)
        setEditedSubject(data.draft.subject)
        setEditedPreheader(data.draft.preheader)
        setEditedHtml(data.draft.body_html)
        setEditedText(data.draft.body_text)
        setStep('preview')
        setError(null)
      }
    },
    onError: (err) => {
      setError(err.response?.data?.detail || 'Failed to generate email. Please try again.')
    },
  })

  // Send mutation
  const sendMutation = useMutation({
    mutationFn: async (sendData) => {
      const res = await emailAgentApi.send(sendData)
      return res.data
    },
    onSuccess: (data) => {
      if (data.success) {
        setSendResult(data)
        setStep('sent')
        setShowConfirm(false)
        queryClient.invalidateQueries({ queryKey: ['emailAgent', 'history'] })
      }
    },
    onError: (err) => {
      setShowConfirm(false)
      setError(err.response?.data?.detail || 'Failed to send email.')
    },
  })

  // Update iframe when HTML changes
  const updateIframe = useCallback(() => {
    if (iframeRef.current) {
      const doc = iframeRef.current.contentDocument
      if (doc) {
        doc.open()
        doc.write(editedHtml)
        doc.close()
      }
    }
  }, [editedHtml])

  useEffect(() => {
    updateIframe()
  }, [updateIframe])

  const handleGenerate = () => {
    if (!brief.what_happened.trim()) {
      setError('Please fill in what happened this week.')
      return
    }
    setError(null)
    generateMutation.mutate(brief)
  }

  const handleSend = () => {
    if (!editedSubject.trim()) {
      setError('Subject line cannot be empty.')
      return
    }
    setError(null)
    sendMutation.mutate({
      subject: editedSubject,
      preheader: editedPreheader,
      body_html: editedHtml,
      body_text: editedText,
      brief_summary: brief.what_happened.substring(0, 100),
    })
  }

  const handleStartNew = () => {
    setStep('brief')
    setBrief({ what_happened: '', coming_up: '', tone: 'Friendly & casual', promo_mention: '', subject_idea: '' })
    setDraft(null)
    setSendResult(null)
    setError(null)
  }

  const subscriberCount = audienceData?.count || 0
  const isConfigured = audienceData?.configured !== false

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Weekly Email</h1>
          <p className="mt-1 text-sm text-gray-500">
            Write and send your weekly update to the OPENDC client list
          </p>
        </div>
        {isConfigured && subscriberCount > 0 && (
          <div className="text-sm text-gray-500">
            <span className="font-medium text-gray-700">{subscriberCount.toLocaleString()}</span> subscribers
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex justify-between items-start">
            <p className="text-sm text-red-700">{error}</p>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 ml-4 text-lg leading-none">&times;</button>
          </div>
        </div>
      )}

      {/* Not configured warning */}
      {audienceData && !isConfigured && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800 font-medium">Mailchimp not configured</p>
          <p className="text-sm text-yellow-700 mt-1">
            Set MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, and MAILCHIMP_AUDIENCE_ID in your .env file.
            See MAILCHIMP_SETUP.md for instructions.
          </p>
        </div>
      )}

      {/* STEP 1: Brief Form */}
      {step === 'brief' && (
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Brief the AI</h2>
            <p className="text-sm text-gray-500 mt-1">Fill in a few fields and Claude will write the email in Joey's voice</p>
          </div>
          <div className="p-6 space-y-5">
            {/* What happened */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                What happened this week? <span className="text-red-500">*</span>
              </label>
              <textarea
                value={brief.what_happened}
                onChange={(e) => setBrief({ ...brief, what_happened: e.target.value })}
                rows={4}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Shipped a big commercial job in Lethbridge, got new Clopay stock in, trained two new installers..."
              />
            </div>

            {/* Coming up */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anything coming up?
              </label>
              <textarea
                value={brief.coming_up}
                onChange={(e) => setBrief({ ...brief, coming_up: e.target.value })}
                rows={3}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Spring rush starting, lead times tightening on steel doors..."
              />
            </div>

            {/* Tone */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Tone this week
              </label>
              <div className="flex flex-wrap gap-2">
                {TONE_OPTIONS.map((tone) => (
                  <button
                    key={tone}
                    onClick={() => setBrief({ ...brief, tone })}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                      brief.tone === tone
                        ? 'bg-odc-600 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {tone}
                  </button>
                ))}
              </div>
            </div>

            {/* Promo */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Any specific product or promo to mention?
              </label>
              <input
                type="text"
                value={brief.promo_mention}
                onChange={(e) => setBrief({ ...brief, promo_mention: e.target.value })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Optional — leave blank if nothing specific"
              />
            </div>

            {/* Subject idea */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email subject line idea
              </label>
              <input
                type="text"
                value={brief.subject_idea}
                onChange={(e) => setBrief({ ...brief, subject_idea: e.target.value })}
                className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                placeholder="Optional — Claude will generate one if left blank"
              />
            </div>

            {/* Generate button */}
            <div className="pt-2">
              <button
                onClick={handleGenerate}
                disabled={generateMutation.isPending || !brief.what_happened.trim()}
                className="inline-flex items-center px-5 py-2.5 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generateMutation.isPending ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating...
                  </>
                ) : (
                  'Generate Email'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 2: Preview / Edit */}
      {step === 'preview' && draft && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Edit panel */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-lg font-medium text-gray-900">Edit</h2>
                <div className="flex gap-2">
                  <button
                    onClick={() => setStep('brief')}
                    className="text-sm text-gray-500 hover:text-gray-700"
                  >
                    Edit Brief
                  </button>
                  <button
                    onClick={handleGenerate}
                    disabled={generateMutation.isPending}
                    className="text-sm text-odc-600 hover:text-odc-700 font-medium"
                  >
                    {generateMutation.isPending ? 'Regenerating...' : 'Regenerate'}
                  </button>
                </div>
              </div>
              <div className="p-6 space-y-4">
                {/* Subject */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subject line</label>
                  <input
                    type="text"
                    value={editedSubject}
                    onChange={(e) => setEditedSubject(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                  />
                </div>

                {/* Preheader */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Preheader text</label>
                  <input
                    type="text"
                    value={editedPreheader}
                    onChange={(e) => setEditedPreheader(e.target.value)}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 sm:text-sm"
                  />
                </div>

                {/* HTML body */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email body (HTML)</label>
                  <textarea
                    value={editedHtml}
                    onChange={(e) => setEditedHtml(e.target.value)}
                    rows={16}
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-odc-500 focus:ring-odc-500 font-mono text-xs"
                  />
                </div>

                {/* Internal notes */}
                {draft.internal_notes && (
                  <div className="bg-gray-50 rounded-md p-3">
                    <p className="text-xs font-medium text-gray-500 mb-1">AI Notes</p>
                    <p className="text-sm text-gray-600">{draft.internal_notes}</p>
                  </div>
                )}
              </div>
            </div>

            {/* Right: Preview panel */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <h2 className="text-lg font-medium text-gray-900">Preview</h2>
                <div className="flex bg-gray-100 rounded-md p-0.5">
                  <button
                    onClick={() => setPreviewWidth('desktop')}
                    className={`px-3 py-1 text-xs font-medium rounded ${
                      previewWidth === 'desktop' ? 'bg-white shadow text-gray-900' : 'text-gray-500'
                    }`}
                  >
                    Desktop
                  </button>
                  <button
                    onClick={() => setPreviewWidth('mobile')}
                    className={`px-3 py-1 text-xs font-medium rounded ${
                      previewWidth === 'mobile' ? 'bg-white shadow text-gray-900' : 'text-gray-500'
                    }`}
                  >
                    Mobile
                  </button>
                </div>
              </div>

              {/* Inbox simulation header */}
              <div className="bg-gray-50 px-6 py-3 border-b border-gray-100">
                <p className="text-sm font-medium text-gray-900 truncate">{editedSubject || '(No subject)'}</p>
                <p className="text-xs text-gray-500 truncate mt-0.5">{editedPreheader}</p>
              </div>

              {/* Email preview iframe */}
              <div className="bg-gray-100 p-4 flex justify-center" style={{ minHeight: '500px' }}>
                <div
                  className="bg-white shadow-lg rounded-sm overflow-hidden transition-all duration-200"
                  style={{ width: previewWidth === 'desktop' ? '600px' : '375px', maxWidth: '100%' }}
                >
                  <iframe
                    ref={iframeRef}
                    title="Email Preview"
                    style={{ width: '100%', minHeight: '480px', border: 'none' }}
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Send button row */}
          <div className="bg-white shadow rounded-lg px-6 py-4 flex items-center justify-between">
            <button
              onClick={() => setStep('brief')}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Back to Brief
            </button>
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(editedHtml)
                  setError(null)
                }}
                className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
              >
                Copy HTML
              </button>
              <button
                onClick={() => setShowConfirm(true)}
                disabled={!editedSubject.trim() || !isConfigured}
                className="inline-flex items-center px-5 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-odc-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Send via Mailchimp
              </button>
            </div>
          </div>
        </>
      )}

      {/* STEP 3: Success */}
      {step === 'sent' && sendResult && (
        <div className="bg-white shadow rounded-lg p-8 text-center">
          <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
            <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Email Sent!</h2>
          <p className="text-gray-600 mb-6">
            Your weekly update has been sent to{' '}
            <span className="font-medium">{sendResult.recipient_count?.toLocaleString()}</span> subscribers.
          </p>
          <div className="bg-gray-50 rounded-lg p-4 max-w-sm mx-auto text-left text-sm space-y-1 mb-6">
            <p><span className="text-gray-500">Campaign ID:</span> <span className="font-mono text-gray-700">{sendResult.campaign_id}</span></p>
            <p><span className="text-gray-500">Sent at:</span> <span className="text-gray-700">{new Date(sendResult.sent_at).toLocaleString()}</span></p>
          </div>
          <button
            onClick={handleStartNew}
            className="inline-flex items-center px-5 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-odc-600 hover:bg-odc-700"
          >
            Write Another Email
          </button>
        </div>
      )}

      {/* Send confirmation dialog */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4">
            <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={() => setShowConfirm(false)} />
            <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-sm w-full">
              <h3 className="text-lg font-medium text-gray-900 mb-2">Confirm Send</h3>
              <p className="text-sm text-gray-600 mb-4">
                Send this email to{' '}
                <span className="font-medium">{subscriberCount.toLocaleString()}</span> subscribers?
              </p>
              <p className="text-sm text-gray-500 mb-6 truncate">
                Subject: <span className="font-medium text-gray-700">{editedSubject}</span>
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowConfirm(false)}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSend}
                  disabled={sendMutation.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-odc-600 border border-transparent rounded-md hover:bg-odc-700 disabled:opacity-50"
                >
                  {sendMutation.isPending ? 'Sending...' : 'Send Now'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Past Emails */}
      <div className="bg-white shadow rounded-lg">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-medium text-gray-900">Past Emails</h2>
        </div>
        <div className="overflow-x-auto">
          {historyLoading ? (
            <div className="p-6 text-center text-sm text-gray-500">Loading history...</div>
          ) : !historyData?.campaigns?.length ? (
            <div className="p-6 text-center text-sm text-gray-500">No emails sent yet</div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Subject</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Recipients</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Mailchimp</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {historyData.campaigns.map((c) => (
                  <tr key={c.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {c.sent_at ? new Date(c.sent_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900 max-w-xs truncate">{c.subject}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{c.recipient_count?.toLocaleString()}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {c.mailchimp_campaign_id && (
                        <a
                          href={`https://${audienceData?.audience_name ? '' : ''}admin.mailchimp.com/reports/summary?id=${c.mailchimp_campaign_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-odc-600 hover:text-odc-700"
                        >
                          View Report
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default WeeklyEmail
