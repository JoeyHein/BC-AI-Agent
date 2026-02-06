import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { chatApi } from '../../api/client'
import ChatHeader from './ChatHeader'
import MessageList from './MessageList'
import MessageInput from './MessageInput'

/**
 * Global AI Chat Box Component
 *
 * A floating chat interface that allows users to control
 * Business Central through natural language commands.
 *
 * Features:
 * - Context-aware (knows what page/data the user is viewing)
 * - Executes actions (schedule orders, query data, etc.)
 * - Conversation persistence
 */
function ChatBox({ onAction }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [error, setError] = useState(null)
  const location = useLocation()
  const messagesEndRef = useRef(null)

  // Scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Build context from current route
  const getPageContext = () => {
    const path = location.pathname
    const context = { page: 'dashboard' }

    if (path.includes('production')) {
      context.page = 'production_calendar'
    } else if (path.includes('orders')) {
      context.page = 'orders'
    } else if (path.includes('reviews') || path.includes('quotes')) {
      context.page = 'quotes'
    } else if (path.includes('analytics')) {
      context.page = 'analytics'
    } else if (path.includes('customers')) {
      context.page = 'customers'
    }

    return context
  }

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: input,
      createdAt: new Date().toISOString()
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setError(null)

    try {
      const context = getPageContext()
      const response = await chatApi.sendMessage(input, context, conversationId)

      if (response.data.success) {
        // Store conversation ID for continuity
        if (response.data.conversation_id) {
          setConversationId(response.data.conversation_id)
        }

        // Add assistant response
        const assistantMessage = {
          id: Date.now() + 1,
          role: 'assistant',
          content: response.data.response,
          actions: response.data.actions_taken || [],
          tokensUsed: response.data.tokens_used,
          createdAt: new Date().toISOString()
        }
        setMessages(prev => [...prev, assistantMessage])

        // Notify parent if actions were taken (for refreshing data)
        if (response.data.actions_taken?.length > 0 && onAction) {
          onAction(response.data.actions_taken)
        }
      } else {
        setError(response.data.response || 'Failed to get response')
        setMessages(prev => [...prev, {
          id: Date.now() + 1,
          role: 'error',
          content: response.data.response || 'Failed to send message',
          createdAt: new Date().toISOString()
        }])
      }
    } catch (err) {
      console.error('Chat error:', err)
      setError(err.message || 'Failed to send message')
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'error',
        content: 'Failed to connect to the AI service. Please try again.',
        createdAt: new Date().toISOString()
      }])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearChat = () => {
    setMessages([])
    setConversationId(null)
    setError(null)
  }

  const toggleChat = () => {
    setIsOpen(!isOpen)
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={toggleChat}
        className={`fixed bottom-6 right-6 w-14 h-14 rounded-full shadow-lg flex items-center justify-center text-white z-50 transition-all duration-200 ${
          isOpen
            ? 'bg-gray-600 hover:bg-gray-700'
            : 'bg-indigo-600 hover:bg-indigo-700'
        }`}
        title={isOpen ? 'Close chat' : 'Open AI assistant'}
      >
        {isOpen ? (
          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        )}
      </button>

      {/* Chat panel */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 w-96 h-[500px] bg-white rounded-lg shadow-xl border border-gray-200 flex flex-col z-50">
          <ChatHeader
            onClose={toggleChat}
            onClear={clearChat}
            messageCount={messages.length}
          />

          <MessageList
            messages={messages}
            isLoading={isLoading}
            messagesEndRef={messagesEndRef}
          />

          <MessageInput
            value={input}
            onChange={setInput}
            onSend={sendMessage}
            onKeyPress={handleKeyPress}
            disabled={isLoading}
            placeholder="Ask me to schedule orders, check status..."
          />
        </div>
      )}
    </>
  )
}

export default ChatBox
