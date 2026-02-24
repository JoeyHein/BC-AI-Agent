import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { productionApi } from '../api/client'
import { format, startOfMonth, endOfMonth, eachDayOfInterval, isSameMonth, isToday, addMonths, subMonths, isWeekend, parseISO } from 'date-fns'

function ProductionCalendar() {
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState(null)
  const [showScheduleModal, setShowScheduleModal] = useState(false)
  const [draggedOrder, setDraggedOrder] = useState(null)
  const queryClient = useQueryClient()

  const startDate = format(startOfMonth(currentMonth), 'yyyy-MM-dd')
  const endDate = format(endOfMonth(currentMonth), 'yyyy-MM-dd')

  // Fetch production API status
  const { data: apiStatus } = useQuery({
    queryKey: ['productionStatus'],
    queryFn: async () => {
      const response = await productionApi.getStatus()
      return response.data
    }
  })

  // Fetch capacity for the month
  const { data: capacityData, isLoading: capacityLoading } = useQuery({
    queryKey: ['productionCapacity', startDate, endDate],
    queryFn: async () => {
      const response = await productionApi.getCapacity(startDate, endDate)
      return response.data
    }
  })

  // State for showing all orders or just unscheduled
  const [showAllOrders, setShowAllOrders] = useState(false)

  // Fetch all open sales orders for the side panel
  const { data: openOrdersData, isLoading: openOrdersLoading } = useQuery({
    queryKey: ['openOrders', showAllOrders],
    queryFn: async () => {
      const response = await productionApi.getOpenOrders(!showAllOrders) // true = only unscheduled
      return response.data
    }
  })

  // Fetch scheduled summary for the month (SO# display on calendar)
  const { data: scheduledSummary } = useQuery({
    queryKey: ['scheduledSummary', startDate, endDate],
    queryFn: async () => {
      const response = await productionApi.getScheduledSummary(startDate, endDate)
      return response.data
    }
  })

  // Fetch lead times
  const { data: leadTimes } = useQuery({
    queryKey: ['productionLeadTimes'],
    queryFn: async () => {
      const response = await productionApi.getLeadTimes()
      return response.data
    }
  })

  // Schedule sales order mutation (drag & drop)
  const scheduleMutation = useMutation({
    mutationFn: async ({ salesOrderId, scheduledDate }) => {
      const response = await productionApi.scheduleOrder(salesOrderId, scheduledDate)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
      queryClient.invalidateQueries({ queryKey: ['productionTasks'] })
      queryClient.invalidateQueries({ queryKey: ['scheduledSummary'] })
    },
    onError: (error) => {
      console.error('Schedule error:', error)
      alert(`Failed to schedule order: ${error.message || 'Unknown error'}`)
    }
  })

  // Schedule production order mutation (for orphan work orders)
  const scheduleProductionOrderMutation = useMutation({
    mutationFn: async ({ productionOrderId, scheduledDate }) => {
      const response = await productionApi.scheduleProductionOrder(productionOrderId, scheduledDate)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
      queryClient.invalidateQueries({ queryKey: ['productionTasks'] })
      queryClient.invalidateQueries({ queryKey: ['scheduledSummary'] })
    },
    onError: (error) => {
      console.error('Schedule production order error:', error)
      alert(`Failed to schedule work order: ${error.message || 'Unknown error'}`)
    }
  })

  // Calculate schedule mutation
  const calculateScheduleMutation = useMutation({
    mutationFn: async (scheduleData) => {
      const response = await productionApi.calculateSchedule(scheduleData)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      setShowScheduleModal(false)
    }
  })

  // Build calendar days
  const calendarDays = useMemo(() => {
    const monthStart = startOfMonth(currentMonth)
    const monthEnd = endOfMonth(currentMonth)
    const days = eachDayOfInterval({ start: monthStart, end: monthEnd })

    // Create capacity map for quick lookup
    const capacityMap = {}
    if (capacityData?.capacity) {
      capacityData.capacity.forEach(c => {
        capacityMap[c.date] = c
      })
    }

    // Create scheduled orders map for quick lookup
    const scheduledMap = scheduledSummary?.byDate || {}

    return days.map(day => {
      const dateStr = format(day, 'yyyy-MM-dd')
      const capacity = capacityMap[dateStr]
      const scheduledOrders = scheduledMap[dateStr] || []
      return {
        date: day,
        dateStr,
        isWeekend: isWeekend(day),
        isToday: isToday(day),
        capacity: capacity?.availableHours || 0,
        scheduled: capacity?.scheduledHours || 0,
        utilization: capacity ? (capacity.scheduledHours / capacity.availableHours * 100) : 0,
        orders: capacity?.orders || [],
        scheduledOrders: scheduledOrders // SO# for display
      }
    })
  }, [currentMonth, capacityData, scheduledSummary])

  const prevMonth = () => setCurrentMonth(subMonths(currentMonth, 1))
  const nextMonth = () => setCurrentMonth(addMonths(currentMonth, 1))

  const getUtilizationColor = (utilization) => {
    if (utilization === 0) return 'bg-gray-50'
    if (utilization < 50) return 'bg-green-100'
    if (utilization < 80) return 'bg-yellow-100'
    if (utilization < 100) return 'bg-orange-100'
    return 'bg-red-100'
  }

  const getUtilizationTextColor = (utilization) => {
    if (utilization === 0) return 'text-gray-400'
    if (utilization < 50) return 'text-green-700'
    if (utilization < 80) return 'text-yellow-700'
    if (utilization < 100) return 'text-orange-700'
    return 'text-red-700'
  }

  // Drag and Drop handlers
  const handleDragStart = (e, order) => {
    setDraggedOrder(order)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', JSON.stringify(order))
  }

  const handleDragOver = (e, day) => {
    e.preventDefault()  // Must call preventDefault first to allow drop
    if (day.isWeekend) {
      e.dataTransfer.dropEffect = 'none'
      return
    }
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e, day) => {
    e.preventDefault()
    if (day.isWeekend) return

    // Read from dataTransfer in case draggedOrder state was cleared by dragEnd
    let orderData = draggedOrder
    if (!orderData) {
      try {
        const data = e.dataTransfer.getData('text/plain')
        if (data) {
          orderData = JSON.parse(data)
        }
      } catch (err) {
        console.error('Failed to parse drag data:', err)
        return
      }
    }

    if (!orderData) return

    const dateStr = format(day.date, 'yyyy-MM-dd')
    const salesOrderId = orderData.salesOrderId || orderData.id

    if (salesOrderId) {
      // Regular sales order - schedule via sales order
      scheduleMutation.mutate({
        salesOrderId: salesOrderId,
        scheduledDate: dateStr
      })
    } else if (orderData.workOrders && orderData.workOrders.length > 0) {
      // Orphan work order - schedule via production order
      const productionOrderId = orderData.workOrders[0].id
      if (productionOrderId) {
        scheduleProductionOrderMutation.mutate({
          productionOrderId: productionOrderId,
          scheduledDate: dateStr
        })
      }
    }

    setDraggedOrder(null)
  }

  const handleDragEnd = () => {
    setDraggedOrder(null)
  }

  return (
    <div className="flex gap-6">
      {/* Main Calendar Area */}
      <div className="flex-1 space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Production Calendar</h1>
            <p className="mt-1 text-sm text-gray-500">Schedule and track production orders</p>
          </div>
          <div className="flex items-center space-x-4">
            {/* API Status Indicator */}
            <div className={`flex items-center px-3 py-1 rounded-full text-xs font-medium ${
              apiStatus?.apiAvailable
                ? 'bg-green-100 text-green-800'
                : 'bg-yellow-100 text-yellow-800'
            }`}>
              <span className={`w-2 h-2 rounded-full mr-2 ${
                apiStatus?.apiAvailable ? 'bg-green-500' : 'bg-yellow-500'
              }`}></span>
              {apiStatus?.apiAvailable ? 'BC Connected' : 'Local Mode'}
            </div>
            <button
              onClick={() => setShowScheduleModal(true)}
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700"
            >
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Schedule Production
            </button>
          </div>
        </div>

        {/* API Warning */}
        {!apiStatus?.apiAvailable && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex">
              <svg className="w-5 h-5 text-yellow-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <div>
                <h3 className="text-sm font-medium text-yellow-800">BC Production API Not Available</h3>
                <p className="mt-1 text-sm text-yellow-700">
                  Schedule calculations work locally. To create actual production orders in BC,
                  ask your BC admin to publish the Production Orders page as an OData web service.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Calendar */}
        <div className="bg-white shadow rounded-lg">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <button
              onClick={prevMonth}
              className="p-2 hover:bg-gray-100 rounded-full"
            >
              <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <h2 className="text-lg font-semibold text-gray-900">
              {format(currentMonth, 'MMMM yyyy')}
            </h2>
            <button
              onClick={nextMonth}
              className="p-2 hover:bg-gray-100 rounded-full"
            >
              <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>

          {/* Calendar Grid */}
          <div className="p-4">
            {/* Day Headers */}
            <div className="grid grid-cols-7 mb-2">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
                <div key={day} className="text-center text-sm font-medium text-gray-500 py-2">
                  {day}
                </div>
              ))}
            </div>

            {/* Calendar Days */}
            {capacityLoading ? (
              <div className="flex justify-center items-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
              </div>
            ) : (
              <div className="grid grid-cols-7 gap-1">
                {/* Empty cells for days before month starts */}
                {Array.from({ length: startOfMonth(currentMonth).getDay() }).map((_, i) => (
                  <div key={`empty-${i}`} className="h-24 bg-gray-50 rounded"></div>
                ))}

                {/* Actual days */}
                {calendarDays.map(day => (
                  <div
                    key={day.dateStr}
                    onClick={() => !day.isWeekend && setSelectedDate(day)}
                    onDragOver={(e) => handleDragOver(e, day)}
                    onDrop={(e) => handleDrop(e, day)}
                    className={`h-24 rounded border cursor-pointer transition-all ${
                      day.isWeekend
                        ? 'bg-gray-100 border-gray-200 cursor-not-allowed'
                        : `${getUtilizationColor(day.utilization)} border-gray-200 hover:border-odc-400`
                    } ${day.isToday ? 'ring-2 ring-odc-500' : ''} ${
                      selectedDate?.dateStr === day.dateStr ? 'ring-2 ring-odc-600' : ''
                    } ${draggedOrder && !day.isWeekend ? 'ring-2 ring-dashed ring-odc-300' : ''}`}
                  >
                    <div className="p-2 h-full flex flex-col pointer-events-none">
                      <div className={`text-sm font-medium ${
                        day.isToday ? 'text-odc-600' : day.isWeekend ? 'text-gray-400' : 'text-gray-900'
                      }`}>
                        {format(day.date, 'd')}
                      </div>
                      {!day.isWeekend && (
                        <>
                          <div className={`text-xs mt-1 ${getUtilizationTextColor(day.utilization)}`}>
                            {day.utilization > 0 ? `${Math.round(day.utilization)}%` : '-'}
                          </div>
                          {/* Display scheduled SO# */}
                          {day.scheduledOrders && day.scheduledOrders.length > 0 && (
                            <div className="mt-1 space-y-0.5 overflow-hidden flex-1">
                              {day.scheduledOrders.slice(0, 3).map((so, idx) => (
                                <div
                                  key={so.id || idx}
                                  className="text-xs truncate px-1 py-0.5 bg-blue-100 text-blue-800 rounded font-medium"
                                  title={`${so.bcOrderNumber} - ${so.customerName}`}
                                >
                                  {so.bcOrderNumber}
                                </div>
                              ))}
                              {day.scheduledOrders.length > 3 && (
                                <div className="text-xs text-gray-500 px-1">
                                  +{day.scheduledOrders.length - 3} more
                                </div>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
            <div className="flex items-center justify-center space-x-6 text-sm">
              <div className="flex items-center">
                <div className="w-4 h-4 rounded bg-gray-50 border border-gray-200 mr-2"></div>
                <span className="text-gray-600">Available</span>
              </div>
              <div className="flex items-center">
                <div className="w-4 h-4 rounded bg-green-100 mr-2"></div>
                <span className="text-gray-600">&lt;50%</span>
              </div>
              <div className="flex items-center">
                <div className="w-4 h-4 rounded bg-yellow-100 mr-2"></div>
                <span className="text-gray-600">50-80%</span>
              </div>
              <div className="flex items-center">
                <div className="w-4 h-4 rounded bg-orange-100 mr-2"></div>
                <span className="text-gray-600">80-100%</span>
              </div>
              <div className="flex items-center">
                <div className="w-4 h-4 rounded bg-red-100 mr-2"></div>
                <span className="text-gray-600">Over capacity</span>
              </div>
            </div>
          </div>
        </div>

        {/* Selected Day Detail */}
        {selectedDate && (
          <SelectedDayDetail
            day={selectedDate}
            onClose={() => setSelectedDate(null)}
          />
        )}

        {/* Lead Times Card */}
        {leadTimes && (
          <div className="bg-white shadow rounded-lg p-6">
            <h3 className="text-lg font-medium text-gray-900 mb-4">Production Lead Times</h3>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
              {leadTimes.leadTimes?.map(lt => (
                <div key={lt.itemPrefix} className="bg-gray-50 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-odc-600">{lt.leadTimeDays}</div>
                  <div className="text-xs text-gray-500 mt-1">days</div>
                  <div className="text-sm font-medium text-gray-700 mt-2">{lt.description}</div>
                  <div className="text-xs text-gray-400">{lt.itemPrefix}*</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Open Sales Orders Side Panel */}
      <OpenOrdersPanel
        orders={openOrdersData?.salesOrders || []}
        isLoading={openOrdersLoading}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        showAllOrders={showAllOrders}
        onToggleShowAll={() => setShowAllOrders(!showAllOrders)}
        totalCount={openOrdersData?.count || 0}
      />

      {/* Schedule Modal */}
      {showScheduleModal && (
        <ScheduleModal
          onClose={() => setShowScheduleModal(false)}
          onSchedule={(data) => calculateScheduleMutation.mutate(data)}
          isLoading={calculateScheduleMutation.isPending}
          result={calculateScheduleMutation.data}
        />
      )}
    </div>
  )
}

function OpenOrdersPanel({ orders, isLoading, onDragStart, onDragEnd, showAllOrders, onToggleShowAll, totalCount }) {
  const [expandedOrders, setExpandedOrders] = useState({})
  const [draggedWorkOrder, setDraggedWorkOrder] = useState(null)
  const [dropTargetOrderId, setDropTargetOrderId] = useState(null)
  const [selectedDates, setSelectedDates] = useState({})  // Track selected date per order
  const queryClient = useQueryClient()

  // Schedule order mutation (date picker method)
  const scheduleOrderMutation = useMutation({
    mutationFn: async ({ salesOrderId, scheduledDate }) => {
      const response = await productionApi.scheduleOrder(salesOrderId, scheduledDate)
      return response.data
    },
    onSuccess: (data, variables) => {
      // Clear the selected date for this order
      setSelectedDates(prev => {
        const newDates = { ...prev }
        delete newDates[variables.salesOrderId]
        return newDates
      })
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
      queryClient.invalidateQueries({ queryKey: ['productionTasks'] })
      queryClient.invalidateQueries({ queryKey: ['scheduledSummary'] })
    },
    onError: (error) => {
      alert(`Failed to schedule order: ${error.message || 'Unknown error'}`)
    }
  })

  // Unschedule order mutation
  const unscheduleOrderMutation = useMutation({
    mutationFn: async (salesOrderId) => {
      const response = await productionApi.unscheduleOrder(salesOrderId)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
      queryClient.invalidateQueries({ queryKey: ['productionTasks'] })
      queryClient.invalidateQueries({ queryKey: ['scheduledSummary'] })
    },
    onError: (error) => {
      alert(`Failed to unschedule order: ${error.message || 'Unknown error'}`)
    }
  })

  // Link work order mutation
  const linkWorkOrderMutation = useMutation({
    mutationFn: async ({ workOrderId, salesOrderId }) => {
      const response = await productionApi.linkWorkOrder(workOrderId, salesOrderId)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
      queryClient.invalidateQueries({ queryKey: ['productionTasks'] })
    }
  })

  const handleScheduleOrder = (orderId) => {
    const selectedDate = selectedDates[orderId]
    if (!selectedDate) {
      alert('Please select a date first')
      return
    }
    scheduleOrderMutation.mutate({
      salesOrderId: orderId,
      scheduledDate: selectedDate
    })
  }

  const handleDateChange = (orderId, date) => {
    setSelectedDates(prev => ({ ...prev, [orderId]: date }))
  }

  const toggleOrder = (orderId) => {
    setExpandedOrders(prev => ({ ...prev, [orderId]: !prev[orderId] }))
  }

  // Handle work order drag start
  const handleWorkOrderDragStart = (e, workOrder, parentOrder) => {
    e.stopPropagation()
    setDraggedWorkOrder({ ...workOrder, parentOrderId: parentOrder.id })
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('application/json', JSON.stringify({ type: 'workOrder', workOrder }))
  }

  // Handle drag over sales order (for linking)
  const handleSalesOrderDragOver = (e, order) => {
    // Only allow dropping work orders on sales orders (not orphans)
    if (!draggedWorkOrder || !order.id) return
    // Don't allow dropping on the same parent
    if (draggedWorkOrder.parentOrderId === order.id) return

    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDropTargetOrderId(order.id)
  }

  const handleSalesOrderDragLeave = () => {
    setDropTargetOrderId(null)
  }

  // Handle drop on sales order (link work order)
  const handleSalesOrderDrop = (e, targetOrder) => {
    e.preventDefault()
    e.stopPropagation()
    setDropTargetOrderId(null)

    if (!draggedWorkOrder || !targetOrder.id) return

    linkWorkOrderMutation.mutate({
      workOrderId: draggedWorkOrder.id,
      salesOrderId: targetOrder.id
    })

    setDraggedWorkOrder(null)
  }

  const handleWorkOrderDragEnd = () => {
    setDraggedWorkOrder(null)
    setDropTargetOrderId(null)
  }

  const getScheduleStatus = (order) => {
    if (order.totalTasks === 0) return { color: 'gray', label: 'No tasks' }
    if (order.isFullyScheduled) return { color: 'green', label: 'Scheduled' }
    if (order.scheduledTasks > 0) return { color: 'yellow', label: 'Partial' }
    return { color: 'red', label: 'Unscheduled' }
  }

  const statusColors = {
    green: 'bg-green-100 text-green-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    red: 'bg-red-100 text-red-700',
    gray: 'bg-gray-100 text-gray-500'
  }

  return (
    <div className="w-96 flex-shrink-0">
      <div className="bg-white shadow rounded-lg h-fit max-h-[calc(100vh-200px)] flex flex-col">
        <div className="px-4 py-3 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-medium text-gray-900">
              {showAllOrders ? 'All Orders' : 'Open Orders'}
            </h3>
            <button
              onClick={onToggleShowAll}
              className="text-xs text-odc-600 hover:text-odc-800 font-medium"
            >
              {showAllOrders ? 'Show Unscheduled' : 'Show All'}
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {totalCount} orders • Select date and click Schedule
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {isLoading ? (
            <div className="flex justify-center items-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-odc-600"></div>
            </div>
          ) : orders.length > 0 ? (
            orders.map((order, idx) => {
              const status = getScheduleStatus(order)
              const isExpanded = expandedOrders[order.id || idx]

              return (
                <div
                  key={`order-${order.id}-${order.bcOrderNumber || idx}`}
                  className={`border rounded-lg overflow-hidden ${
                    dropTargetOrderId === order.id
                      ? 'border-odc-500 border-2 ring-2 ring-odc-200'
                      : 'border-gray-200'
                  }`}
                  onDragOver={(e) => handleSalesOrderDragOver(e, order)}
                  onDragLeave={handleSalesOrderDragLeave}
                  onDrop={(e) => handleSalesOrderDrop(e, order)}
                >
                  {/* Sales Order Header - Expandable */}
                  <div
                    className={`transition-colors ${
                      dropTargetOrderId === order.id
                        ? 'bg-odc-100'
                        : 'bg-gray-50 hover:bg-gray-100'
                    }`}
                  >
                    <div className="flex items-center">
                      {/* Expand button */}
                      <button
                        onClick={() => toggleOrder(order.id || idx)}
                        className="p-3 hover:bg-gray-200 transition-colors"
                      >
                        <svg className={`w-4 h-4 text-gray-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </button>

                      {/* Draggable area */}
                      <div
                        draggable
                        onDragStart={(e) => onDragStart(e, { salesOrderId: order.id, ...order })}
                        onDragEnd={onDragEnd}
                        className="flex-1 py-2 pr-3 cursor-grab active:cursor-grabbing"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center">
                              <svg className="w-4 h-4 text-blue-500 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              <span className="font-medium text-gray-900 truncate">
                                {order.bcOrderNumber || `Order #${order.id}`}
                              </span>
                            </div>
                            <div className="text-sm text-gray-600 truncate ml-6">
                              {order.customerName}
                            </div>
                          </div>
                          <div className="flex items-center space-x-2 ml-2">
                            <span className={`px-2 py-0.5 text-xs font-medium rounded ${statusColors[status.color]}`}>
                              {status.label}
                            </span>
                            <svg className="w-4 h-4 text-gray-300 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path d="M7 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 2zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 14zm6-8a2 2 0 1 0-.001-4.001A2 2 0 0 0 13 6zm0 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 14z"/>
                            </svg>
                          </div>
                        </div>
                        <div className="flex items-center mt-1 ml-6 text-xs text-gray-500">
                          <span>{order.lineItemCount || 0} line{order.lineItemCount !== 1 ? 's' : ''}</span>
                          <span className="mx-1">•</span>
                          <span>{order.workOrderCount} WO{order.workOrderCount !== 1 ? 's' : ''}</span>
                          <span className="mx-1">•</span>
                          <span>{order.completedTasks}/{order.totalTasks} tasks</span>
                        </div>
                      </div>
                    </div>

                    {/* Scheduling UI */}
                    {order.id && (
                      <div className="px-3 py-2 bg-gray-100 border-t border-gray-200">
                        <div className="flex items-center gap-2">
                          <input
                            type="date"
                            value={selectedDates[order.id] || order.scheduledDate?.split('T')[0] || ''}
                            onChange={(e) => handleDateChange(order.id, e.target.value)}
                            className="flex-1 text-sm border border-gray-300 rounded px-2 py-1 focus:ring-1 focus:ring-odc-500 focus:border-odc-500"
                            min={format(new Date(), 'yyyy-MM-dd')}
                          />
                          <button
                            onClick={() => handleScheduleOrder(order.id)}
                            disabled={scheduleOrderMutation.isPending || !selectedDates[order.id]}
                            className="px-3 py-1 text-sm font-medium text-white bg-odc-600 rounded hover:bg-odc-700 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {scheduleOrderMutation.isPending ? '...' : order.scheduledDate ? 'Update' : 'Schedule'}
                          </button>
                          {order.scheduledDate && (
                            <button
                              onClick={() => unscheduleOrderMutation.mutate(order.id)}
                              disabled={unscheduleOrderMutation.isPending}
                              className="px-2 py-1 text-sm text-red-600 hover:bg-red-50 rounded"
                              title="Remove from schedule"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          )}
                        </div>
                        {order.scheduledDate && (
                          <div className="mt-1 text-xs text-green-600">
                            Currently scheduled: {format(new Date(order.scheduledDate), 'MMM d, yyyy')}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Line Items - Expanded */}
                  {isExpanded && order.lineItems && order.lineItems.length > 0 && (
                    <div className="border-t border-gray-200 bg-white">
                      <div className="px-3 py-1 bg-gray-100 text-xs font-medium text-gray-600 border-b">
                        Line Items ({order.lineItems.length})
                      </div>
                      <div className="divide-y divide-gray-100 max-h-64 overflow-y-auto">
                        {order.lineItems.map((line, lineIdx) => {
                          const isComment = line.lineType === 'Comment'
                          const hasWorkOrder = line.hasLinkedWorkOrder

                          return (
                            <div
                              key={`line-${line.id}-${line.bcLineNo || lineIdx}`}
                              className={`px-3 py-2 text-sm ${isComment ? 'bg-gray-50 italic' : ''}`}
                            >
                              <div className="flex items-start justify-between">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center">
                                    {isComment ? (
                                      <svg className="w-3 h-3 text-gray-400 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
                                      </svg>
                                    ) : (
                                      <svg className="w-3 h-3 text-blue-500 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                                      </svg>
                                    )}
                                    <span className={`truncate ${isComment ? 'text-gray-500' : 'text-gray-700'}`}>
                                      {line.description || line.itemNo || '(No description)'}
                                    </span>
                                  </div>
                                  {!isComment && line.itemNo && (
                                    <div className="ml-5 text-xs text-gray-500">
                                      {line.itemNo} • Qty: {line.quantity}
                                    </div>
                                  )}
                                </div>
                                {hasWorkOrder && (
                                  <span className="ml-2 px-1.5 py-0.5 text-xs bg-green-100 text-green-700 rounded flex-shrink-0">
                                    WO
                                  </span>
                                )}
                              </div>
                              {/* Show linked work orders */}
                              {line.linkedWorkOrders && line.linkedWorkOrders.length > 0 && (
                                <div className="ml-5 mt-1 space-y-1">
                                  {line.linkedWorkOrders.map((wo, woIdx) => (
                                    <div key={woIdx} className="flex items-center text-xs text-odc-600 bg-odc-50 px-2 py-1 rounded">
                                      <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                                      </svg>
                                      {wo.bcProdOrderNumber} ({wo.completedTasks}/{wo.taskCount})
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Unlinked Work Orders - Expanded (orphans or WOs not linked to specific lines) */}
                  {isExpanded && order.workOrders && order.workOrders.filter(wo => !wo.lineItemId).length > 0 && (
                    <div className="border-t border-gray-200 bg-white">
                      <div className="px-3 py-1 bg-yellow-100 text-xs font-medium text-yellow-700 border-b">
                        Unlinked Work Orders ({order.workOrders.filter(wo => !wo.lineItemId).length})
                      </div>
                      <div className="divide-y divide-gray-100">
                        {order.workOrders.filter(wo => !wo.lineItemId).map((wo, woIdx) => {
                          const woStatus = wo.isFullyScheduled ? 'green' : wo.scheduledTasks > 0 ? 'yellow' : 'red'
                          const isOrphan = !order.id
                          return (
                            <div
                              key={`wo-${wo.id}-${wo.bcProdOrderNumber || woIdx}`}
                              draggable={true}
                              onDragStart={(e) => handleWorkOrderDragStart(e, wo, order)}
                              onDragEnd={handleWorkOrderDragEnd}
                              className={`px-4 py-2 hover:bg-gray-50 cursor-grab active:cursor-grabbing ${
                                isOrphan ? 'bg-yellow-50' : ''
                              }`}
                              title={isOrphan ? 'Drag to link to a sales order' : 'Drag to move to another sales order'}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex items-center flex-1 min-w-0">
                                  <svg className="w-4 h-4 text-gray-300 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                    <path d="M7 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 2zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 14zm6-8a2 2 0 1 0-.001-4.001A2 2 0 0 0 13 6zm0 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 14z"/>
                                  </svg>
                                  <svg className="w-4 h-4 text-odc-500 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                                  </svg>
                                  <div className="min-w-0">
                                    <div className="font-medium text-gray-800 text-sm truncate">
                                      {wo.bcProdOrderNumber || `WO-${wo.id}`}
                                    </div>
                                    <div className="text-xs text-gray-500 truncate">
                                      {wo.itemCode} - {wo.itemDescription || 'Item'}
                                    </div>
                                  </div>
                                </div>
                                <div className="flex items-center space-x-2 ml-2">
                                  <span className="text-xs text-gray-500">
                                    {wo.completedTasks}/{wo.taskCount}
                                  </span>
                                  <span className={`w-2 h-2 rounded-full ${
                                    woStatus === 'green' ? 'bg-green-500' :
                                    woStatus === 'yellow' ? 'bg-yellow-500' : 'bg-red-500'
                                  }`}></span>
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {isExpanded && (!order.lineItems || order.lineItems.length === 0) && (!order.workOrders || order.workOrders.length === 0) && (
                    <div className="px-4 py-3 text-center text-sm text-gray-500 bg-gray-50">
                      No line items or work orders
                    </div>
                  )}
                </div>
              )
            })
          ) : (
            <div className="text-center py-8 text-gray-500">
              <svg className="mx-auto h-10 w-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
              <p className="mt-2 text-sm">No open orders</p>
            </div>
          )}
        </div>

        {/* Link success/error message */}
        {linkWorkOrderMutation.isSuccess && (
          <div className="px-4 py-2 bg-green-50 border-t border-green-200">
            <div className="flex items-center text-sm text-green-700">
              <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              Work order linked successfully!
            </div>
          </div>
        )}
        {linkWorkOrderMutation.isError && (
          <div className="px-4 py-2 bg-red-50 border-t border-red-200">
            <div className="flex items-center text-sm text-red-700">
              <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              Failed to link work order
            </div>
          </div>
        )}

        {orders.length > 0 && (
          <div className="px-4 py-3 border-t border-gray-200 bg-gray-50">
            <div className="flex justify-between text-xs text-gray-500">
              <span>{orders.length} sales order{orders.length !== 1 ? 's' : ''}</span>
              <span>{orders.filter(o => !o.isFullyScheduled).length} need scheduling</span>
            </div>
            {draggedWorkOrder && (
              <div className="mt-2 text-xs text-odc-600 font-medium">
                Drop on a sales order to link
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SelectedDayDetail({ day, onClose }) {
  const queryClient = useQueryClient()
  const dateStr = format(day.date, 'yyyy-MM-dd')

  // Expansion state for hierarchical view
  const [expandedSalesOrders, setExpandedSalesOrders] = useState({})
  const [expandedLineItems, setExpandedLineItems] = useState({})
  const [expandedProdOrders, setExpandedProdOrders] = useState({})

  // Fetch tasks with material availability (now grouped by sales order > line item > prod order)
  const { data: tasksData, isLoading: tasksLoading, refetch: refetchTasks } = useQuery({
    queryKey: ['productionTasks', dateStr],
    queryFn: async () => {
      const response = await productionApi.getTasksByDate(dateStr)
      return response.data
    }
  })

  // Complete task mutation
  const completeTaskMutation = useMutation({
    mutationFn: async ({ taskId, userId }) => {
      const response = await productionApi.completeTask(taskId, userId)
      return response.data
    },
    onSuccess: (data) => {
      refetchTasks()
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
    }
  })

  // Ship order mutation
  const shipOrderMutation = useMutation({
    mutationFn: async ({ salesOrderId }) => {
      const response = await productionApi.shipOrder(salesOrderId)
      return response.data
    },
    onSuccess: (data) => {
      refetchTasks()
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
      queryClient.invalidateQueries({ queryKey: ['scheduledSummary'] })
      queryClient.invalidateQueries({ queryKey: ['openOrders'] })
    }
  })

  // Pick line item mutation (for pick/pack orders)
  const pickLineItemMutation = useMutation({
    mutationFn: async ({ lineItemId, quantityPicked, userId }) => {
      const response = await productionApi.pickLineItem(lineItemId, quantityPicked, userId)
      return response.data
    },
    onSuccess: (data) => {
      refetchTasks()
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
    }
  })

  // Unpick line item mutation
  const unpickLineItemMutation = useMutation({
    mutationFn: async ({ lineItemId, userId }) => {
      const response = await productionApi.unpickLineItem(lineItemId, userId)
      return response.data
    },
    onSuccess: (data) => {
      refetchTasks()
      queryClient.invalidateQueries({ queryKey: ['productionCapacity'] })
    }
  })

  const toggleSalesOrder = (soIdx) => {
    setExpandedSalesOrders(prev => ({ ...prev, [soIdx]: !prev[soIdx] }))
  }

  const toggleLineItem = (soIdx, liIdx) => {
    const key = `${soIdx}-${liIdx}`
    setExpandedLineItems(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const toggleProdOrder = (soIdx, liIdx, poIdx) => {
    const key = `${soIdx}-${liIdx}-${poIdx}`
    setExpandedProdOrders(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const getMaterialStatusColor = (status) => {
    switch (status) {
      case 'sufficient': return 'text-green-600 bg-green-100'
      case 'partial': return 'text-yellow-600 bg-yellow-100'
      case 'unavailable': return 'text-red-600 bg-red-100'
      default: return 'text-gray-600 bg-gray-100'
    }
  }

  const getMaterialStatusIcon = (status) => {
    switch (status) {
      case 'sufficient':
        return <svg className="w-4 h-4 text-green-500" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
      case 'partial':
        return <svg className="w-4 h-4 text-yellow-500" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
      case 'unavailable':
        return <svg className="w-4 h-4 text-red-500" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
      default:
        return <svg className="w-4 h-4 text-gray-400" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" /></svg>
    }
  }

  const ChevronIcon = ({ expanded }) => (
    <svg className={`w-5 h-5 text-gray-500 transition-transform ${expanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  )

  const handleTaskComplete = (taskId) => {
    completeTaskMutation.mutate({ taskId, userId: 'shop_floor' })
  }

  const handleShipOrder = (salesOrderId) => {
    if (window.confirm('Ship this order? This will finish the production order and create a shipment in BC.')) {
      shipOrderMutation.mutate({ salesOrderId })
    }
  }

  const handlePickLineItem = (lineItemId, isPicked, quantity) => {
    if (isPicked) {
      // Unpick the item
      unpickLineItemMutation.mutate({ lineItemId, userId: 'shop_floor' })
    } else {
      // Pick the item
      pickLineItemMutation.mutate({ lineItemId, quantityPicked: quantity, userId: 'shop_floor' })
    }
  }

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-lg font-medium text-gray-900">
            {format(day.date, 'EEEE, MMMM d, yyyy')}
          </h3>
          <p className="text-sm text-gray-500">
            {day.scheduled} of {day.capacity} hours scheduled ({Math.round(day.utilization)}% utilization)
          </p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Task Summary */}
      {tasksData && (
        <div className="mb-4 p-3 bg-gray-50 rounded-lg">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">Tasks Progress:</span>
            <span className="font-medium">
              {tasksData.completedTasks} / {tasksData.totalTasks} completed
            </span>
          </div>
          <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-green-500 h-2 rounded-full transition-all"
              style={{ width: `${tasksData.totalTasks > 0 ? (tasksData.completedTasks / tasksData.totalTasks * 100) : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Loading state */}
      {tasksLoading && (
        <div className="flex justify-center items-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-odc-600"></div>
        </div>
      )}

      {/* Sales Orders > Line Items > Production Orders > Tasks Hierarchy */}
      {tasksData?.salesOrders && tasksData.salesOrders.length > 0 ? (
        <div className="space-y-3">
          {tasksData.salesOrders.map((salesOrder, soIdx) => (
            <div key={soIdx} className="border border-gray-200 rounded-lg overflow-hidden">
              {/* Sales Order Header - Expandable */}
              <button
                onClick={() => toggleSalesOrder(soIdx)}
                className={`w-full p-4 text-left flex items-center justify-between ${salesOrder.allComplete ? 'bg-green-50 hover:bg-green-100' : 'bg-blue-50 hover:bg-blue-100'} transition-colors`}
              >
                <div className="flex items-center flex-1">
                  <ChevronIcon expanded={expandedSalesOrders[soIdx]} />
                  <svg className="w-5 h-5 text-blue-600 ml-2 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <div>
                    <span className="font-semibold text-gray-900">
                      {salesOrder.bcOrderNumber || 'No Sales Order'}
                    </span>
                    <span className="ml-2 text-sm text-gray-600">
                      - {salesOrder.customerName}
                    </span>
                  </div>
                </div>
                <div className="flex items-center space-x-4">
                  {salesOrder.orderType === 'pick_pack' ? (
                    <span className="text-xs text-gray-500 bg-white px-2 py-1 rounded">
                      {salesOrder.lineItems?.filter(li => li.isPicked || li.lineType === 'Comment' || !li.quantity).length || 0}/{salesOrder.lineItems?.filter(li => li.lineType !== 'Comment' && li.quantity > 0).length || 0} picked
                    </span>
                  ) : (
                    <span className="text-xs text-gray-500 bg-white px-2 py-1 rounded">
                      {salesOrder.completedTasks}/{salesOrder.totalTasks} tasks
                    </span>
                  )}
                  {salesOrder.status === 'shipped' ? (
                    <span className="inline-flex items-center px-3 py-1 rounded-md text-sm font-medium text-green-700 bg-green-100">
                      <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      Shipped
                    </span>
                  ) : salesOrder.allComplete && salesOrder.salesOrderId && (
                    <span
                      onClick={(e) => { e.stopPropagation(); handleShipOrder(salesOrder.salesOrderId); }}
                      className="inline-flex items-center px-3 py-1 border border-transparent rounded-md text-sm font-medium text-white bg-green-600 hover:bg-green-700 cursor-pointer"
                    >
                      <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                      </svg>
                      Ship
                    </span>
                  )}
                </div>
              </button>

              {/* Line Items within Sales Order - Expandable */}
              {expandedSalesOrders[soIdx] && salesOrder.lineItems && (
                <div className="border-t border-gray-200">
                  {salesOrder.lineItems.map((lineItem, liIdx) => (
                    <div key={liIdx} className="border-b border-gray-100 last:border-b-0">
                      {/* Line Item Header */}
                      <button
                        onClick={() => lineItem.hasProductionOrder && toggleLineItem(soIdx, liIdx)}
                        className={`w-full px-4 py-3 text-left flex items-center justify-between ${lineItem.allComplete ? 'bg-green-50/50' : 'bg-gray-50'} hover:bg-gray-100 transition-colors ${!lineItem.hasProductionOrder ? 'cursor-default' : ''}`}
                      >
                        <div className="flex items-center flex-1 ml-6">
                          {lineItem.hasProductionOrder ? (
                            <ChevronIcon expanded={expandedLineItems[`${soIdx}-${liIdx}`]} />
                          ) : (
                            <span className="w-5 h-5"></span>
                          )}
                          <svg className="w-4 h-4 text-purple-500 ml-2 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                          </svg>
                          <div>
                            <span className="font-medium text-gray-800">
                              {lineItem.itemNo || 'Item'}
                            </span>
                            {lineItem.description && (
                              <span className="ml-2 text-sm text-gray-600">
                                - {lineItem.description}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center space-x-3">
                          <span className="text-sm text-gray-600">
                            Qty: {lineItem.quantity} {lineItem.unitOfMeasure || ''}
                          </span>
                          {lineItem.hasProductionOrder && (
                            <span className="text-xs text-gray-500 bg-white px-2 py-1 rounded">
                              {lineItem.completedTasks}/{lineItem.totalTasks} tasks
                            </span>
                          )}
                          {!lineItem.hasProductionOrder && salesOrder.orderType === 'pick_pack' && lineItem.lineType === 'Item' && lineItem.quantity > 0 && (
                            <div className="flex items-center space-x-2" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={lineItem.isPicked}
                                onChange={() => handlePickLineItem(lineItem.lineItemId, lineItem.isPicked, lineItem.quantity)}
                                disabled={pickLineItemMutation.isPending || unpickLineItemMutation.isPending}
                                className="h-5 w-5 text-green-600 rounded border-gray-300 focus:ring-green-500 disabled:opacity-50"
                              />
                              <span className={`text-xs px-2 py-1 rounded ${lineItem.isPicked ? 'text-green-700 bg-green-100' : 'text-orange-700 bg-orange-100'}`}>
                                {lineItem.isPicked ? 'Picked' : 'To Pick'}
                              </span>
                            </div>
                          )}
                          {!lineItem.hasProductionOrder && (lineItem.lineType === 'Comment' || !lineItem.quantity || lineItem.quantity === 0) && (
                            <span className="text-xs text-gray-400 bg-gray-200 px-2 py-1 rounded">
                              Comment
                            </span>
                          )}
                          {!lineItem.hasProductionOrder && salesOrder.orderType !== 'pick_pack' && lineItem.lineType === 'Item' && lineItem.quantity > 0 && (
                            <span className="text-xs text-gray-400 bg-gray-200 px-2 py-1 rounded">
                              No WO
                            </span>
                          )}
                        </div>
                      </button>

                      {/* Production Orders within Line Item */}
                      {expandedLineItems[`${soIdx}-${liIdx}`] && lineItem.productionOrders && (
                        <div className="bg-white border-t border-gray-100">
                          {lineItem.productionOrders.map((prodOrder, poIdx) => (
                            <div key={poIdx} className="border-b border-gray-50 last:border-b-0">
                              {/* Production Order Header */}
                              <button
                                onClick={() => toggleProdOrder(soIdx, liIdx, poIdx)}
                                className={`w-full px-4 py-2 text-left flex items-center justify-between ${prodOrder.allComplete ? 'bg-green-50/30' : ''} hover:bg-gray-50 transition-colors`}
                              >
                                <div className="flex items-center flex-1 ml-12">
                                  <ChevronIcon expanded={expandedProdOrders[`${soIdx}-${liIdx}-${poIdx}`]} />
                                  <svg className="w-4 h-4 text-odc-500 ml-2 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                                  </svg>
                                  <span className="font-medium text-gray-700">
                                    WO: {prodOrder.bcProdOrderNumber || `WO-${prodOrder.productionOrderId}`}
                                  </span>
                                </div>
                                <span className="text-xs text-gray-500">
                                  {prodOrder.completedTasks}/{prodOrder.totalTasks} tasks
                                </span>
                              </button>

                              {/* Tasks within Production Order */}
                              {expandedProdOrders[`${soIdx}-${liIdx}-${poIdx}`] && (
                                <div className="divide-y divide-gray-50 ml-16">
                                  {prodOrder.tasks.map((task, taskIdx) => (
                                    <div
                                      key={taskIdx}
                                      className={`px-4 py-3 ${task.status === 'completed' ? 'bg-green-50/30' : ''}`}
                                    >
                                      <div className="flex items-center justify-between">
                                        {/* Task checkbox and details */}
                                        <div className="flex items-center space-x-3 flex-1">
                                          <input
                                            type="checkbox"
                                            checked={task.status === 'completed'}
                                            onChange={() => task.status !== 'completed' && handleTaskComplete(task.id)}
                                            disabled={task.status === 'completed' || completeTaskMutation.isPending}
                                            className="h-5 w-5 text-odc-600 rounded border-gray-300 focus:ring-odc-500 disabled:opacity-50"
                                          />
                                          <div className={task.status === 'completed' ? 'line-through text-gray-400' : ''}>
                                            <div className="font-medium text-gray-900">{task.itemNo}</div>
                                            <div className="text-sm text-gray-500">{task.description || 'Component'}</div>
                                          </div>
                                        </div>

                                        {/* Quantity */}
                                        <div className="text-right mr-4">
                                          <div className="text-sm font-medium text-gray-900">
                                            {task.quantityCompleted}/{task.quantityRequired}
                                          </div>
                                          <div className="text-xs text-gray-500">{task.unitOfMeasure || 'EA'}</div>
                                        </div>

                                        {/* Material Status */}
                                        <div className="flex items-center space-x-2">
                                          {getMaterialStatusIcon(task.materialStatus)}
                                          <span className={`px-2 py-1 text-xs font-medium rounded-full ${getMaterialStatusColor(task.materialStatus)}`}>
                                            {task.materialAvailable}/{task.materialNeeded}
                                          </span>
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : !tasksLoading && (
        <div className="text-center py-8 text-gray-500">
          <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="mt-2">No production tasks scheduled</p>
          <p className="text-xs mt-1">Drag orders from the side panel to schedule</p>
        </div>
      )}

      {/* Ship order success message */}
      {shipOrderMutation.isSuccess && shipOrderMutation.data && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center">
            <svg className="w-5 h-5 text-green-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <div>
              <div className="font-medium text-green-800">Order Shipped Successfully!</div>
              <div className="text-sm text-green-700">
                Shipment: {shipOrderMutation.data.shipmentNumber}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error messages */}
      {(completeTaskMutation.isError || shipOrderMutation.isError) && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center">
            <svg className="w-5 h-5 text-red-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <div className="text-sm text-red-700">
              {completeTaskMutation.error?.message || shipOrderMutation.error?.message || 'An error occurred'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ScheduleModal({ onClose, onSchedule, isLoading, result }) {
  const [orders, setOrders] = useState([
    { itemNo: '', quantity: 1, dueDate: '', priority: 'normal' }
  ])
  const [dateRange, setDateRange] = useState({
    startDate: format(new Date(), 'yyyy-MM-dd'),
    endDate: format(addMonths(new Date(), 1), 'yyyy-MM-dd')
  })

  const addOrder = () => {
    setOrders([...orders, { itemNo: '', quantity: 1, dueDate: '', priority: 'normal' }])
  }

  const removeOrder = (index) => {
    setOrders(orders.filter((_, i) => i !== index))
  }

  const updateOrder = (index, field, value) => {
    const newOrders = [...orders]
    newOrders[index][field] = value
    setOrders(newOrders)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const validOrders = orders.filter(o => o.itemNo && o.quantity && o.dueDate)
    if (validOrders.length === 0) return

    onSchedule({
      orders: validOrders,
      startDate: dateRange.startDate,
      endDate: dateRange.endDate,
      workCenterCapacity: 8
    })
  }

  return (
    <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium text-gray-900">Schedule Production</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Schedule Window */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Schedule Window</label>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Start Date</label>
                <input
                  type="date"
                  value={dateRange.startDate}
                  onChange={(e) => setDateRange({ ...dateRange, startDate: e.target.value })}
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">End Date</label>
                <input
                  type="date"
                  value={dateRange.endDate}
                  onChange={(e) => setDateRange({ ...dateRange, endDate: e.target.value })}
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-odc-500 focus:border-odc-500"
                />
              </div>
            </div>
          </div>

          {/* Orders */}
          <div>
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-gray-700">Production Orders</label>
              <button
                type="button"
                onClick={addOrder}
                className="text-sm text-odc-600 hover:text-odc-700"
              >
                + Add Order
              </button>
            </div>

            <div className="space-y-3">
              {orders.map((order, index) => (
                <div key={index} className="bg-gray-50 rounded-lg p-4">
                  <div className="grid grid-cols-12 gap-3">
                    <div className="col-span-4">
                      <label className="block text-xs text-gray-500 mb-1">Item Number</label>
                      <input
                        type="text"
                        placeholder="e.g., HK02-16080-RC"
                        value={order.itemNo}
                        onChange={(e) => updateOrder(index, 'itemNo', e.target.value)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-odc-500 focus:border-odc-500"
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">Quantity</label>
                      <input
                        type="number"
                        min="1"
                        value={order.quantity}
                        onChange={(e) => updateOrder(index, 'quantity', parseInt(e.target.value) || 1)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-odc-500 focus:border-odc-500"
                      />
                    </div>
                    <div className="col-span-3">
                      <label className="block text-xs text-gray-500 mb-1">Due Date</label>
                      <input
                        type="date"
                        value={order.dueDate}
                        onChange={(e) => updateOrder(index, 'dueDate', e.target.value)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-odc-500 focus:border-odc-500"
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">Priority</label>
                      <select
                        value={order.priority}
                        onChange={(e) => updateOrder(index, 'priority', e.target.value)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-odc-500 focus:border-odc-500"
                      >
                        <option value="low">Low</option>
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                      </select>
                    </div>
                    <div className="col-span-1 flex items-end">
                      {orders.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removeOrder(index)}
                          className="p-2 text-red-500 hover:text-red-700"
                        >
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Schedule Result */}
          {result && (
            <div className={`rounded-lg p-4 ${result.success ? 'bg-green-50' : 'bg-yellow-50'}`}>
              <h4 className={`font-medium ${result.success ? 'text-green-800' : 'text-yellow-800'}`}>
                Schedule Result
              </h4>
              <p className={`text-sm mt-1 ${result.success ? 'text-green-700' : 'text-yellow-700'}`}>
                {result.message}
              </p>
              {result.summary && (
                <div className="mt-2 text-sm">
                  <span className="text-green-700">{result.summary.scheduledCount} scheduled</span>
                  {result.summary.unscheduledCount > 0 && (
                    <span className="text-red-700 ml-3">{result.summary.unscheduledCount} could not be scheduled</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-odc-600 hover:bg-odc-700 disabled:opacity-50"
            >
              {isLoading ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  Calculating...
                </>
              ) : (
                'Calculate Schedule'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default ProductionCalendar
