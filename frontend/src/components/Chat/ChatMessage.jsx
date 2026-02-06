/**
 * Chat Message Component
 *
 * Individual message bubble with support for:
 * - User messages (right-aligned, blue)
 * - Assistant messages (left-aligned, white)
 * - Error messages (left-aligned, red)
 * - Action badges (for tool calls)
 */
function ChatMessage({ message }) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'
  const isAssistant = message.role === 'assistant'

  // Format time
  const formatTime = (dateString) => {
    if (!dateString) return ''
    const date = new Date(dateString)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  // Get action summary for badges
  const getActionSummary = (action) => {
    const toolLabels = {
      'schedule_order': 'Scheduled',
      'unschedule_order': 'Unscheduled',
      'get_order_details': 'Looked up',
      'list_unscheduled_orders': 'Listed orders',
      'get_schedule_for_date': 'Checked schedule',
      'ship_order': 'Shipped',
      'sync_from_bc': 'Synced'
    }
    return toolLabels[action.tool] || action.tool
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-2 ${
          isUser
            ? 'bg-indigo-600 text-white'
            : isError
            ? 'bg-red-50 text-red-700 border border-red-200'
            : 'bg-white text-gray-800 border border-gray-200 shadow-sm'
        }`}
      >
        {/* Message content */}
        <div className="text-sm whitespace-pre-wrap">{message.content}</div>

        {/* Action badges for assistant messages */}
        {isAssistant && message.actions && message.actions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {message.actions.map((action, index) => (
              <span
                key={index}
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  action.result?.success
                    ? 'bg-green-100 text-green-800'
                    : 'bg-red-100 text-red-800'
                }`}
                title={action.result?.message || action.result?.error || ''}
              >
                {action.result?.success ? (
                  <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                )}
                {getActionSummary(action)}
              </span>
            ))}
          </div>
        )}

        {/* Timestamp */}
        <div
          className={`text-xs mt-1 ${
            isUser ? 'text-indigo-200' : isError ? 'text-red-400' : 'text-gray-400'
          }`}
        >
          {formatTime(message.createdAt)}
        </div>
      </div>
    </div>
  )
}

export default ChatMessage
