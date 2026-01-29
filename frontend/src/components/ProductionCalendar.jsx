import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { productionApi } from '../api/client'
import { format, startOfMonth, endOfMonth, eachDayOfInterval, isSameMonth, isToday, addMonths, subMonths, isWeekend, parseISO } from 'date-fns'

function ProductionCalendar() {
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState(null)
  const [showScheduleModal, setShowScheduleModal] = useState(false)
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

  // Fetch lead times
  const { data: leadTimes } = useQuery({
    queryKey: ['productionLeadTimes'],
    queryFn: async () => {
      const response = await productionApi.getLeadTimes()
      return response.data
    }
  })

  // Calculate schedule mutation
  const scheduleMutation = useMutation({
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

    return days.map(day => {
      const dateStr = format(day, 'yyyy-MM-dd')
      const capacity = capacityMap[dateStr]
      return {
        date: day,
        dateStr,
        isWeekend: isWeekend(day),
        isToday: isToday(day),
        capacity: capacity?.availableHours || 0,
        scheduled: capacity?.scheduledHours || 0,
        utilization: capacity ? (capacity.scheduledHours / capacity.availableHours * 100) : 0,
        orders: capacity?.orders || []
      }
    })
  }, [currentMonth, capacityData])

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

  return (
    <div className="space-y-6">
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
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700"
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

      {/* Calendar Navigation */}
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
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
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
                  className={`h-24 rounded border cursor-pointer transition-colors ${
                    day.isWeekend
                      ? 'bg-gray-100 border-gray-200 cursor-not-allowed'
                      : `${getUtilizationColor(day.utilization)} border-gray-200 hover:border-indigo-400`
                  } ${day.isToday ? 'ring-2 ring-indigo-500' : ''} ${
                    selectedDate?.dateStr === day.dateStr ? 'ring-2 ring-indigo-600' : ''
                  }`}
                >
                  <div className="p-2 h-full flex flex-col">
                    <div className={`text-sm font-medium ${
                      day.isToday ? 'text-indigo-600' : day.isWeekend ? 'text-gray-400' : 'text-gray-900'
                    }`}>
                      {format(day.date, 'd')}
                    </div>
                    {!day.isWeekend && (
                      <>
                        <div className={`text-xs mt-1 ${getUtilizationTextColor(day.utilization)}`}>
                          {day.utilization > 0 ? `${Math.round(day.utilization)}%` : '-'}
                        </div>
                        {day.orders.length > 0 && (
                          <div className="mt-auto">
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800">
                              {day.orders.length} order{day.orders.length > 1 ? 's' : ''}
                            </span>
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
                <div className="text-2xl font-bold text-indigo-600">{lt.leadTimeDays}</div>
                <div className="text-xs text-gray-500 mt-1">days</div>
                <div className="text-sm font-medium text-gray-700 mt-2">{lt.description}</div>
                <div className="text-xs text-gray-400">{lt.itemPrefix}*</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Schedule Modal */}
      {showScheduleModal && (
        <ScheduleModal
          onClose={() => setShowScheduleModal(false)}
          onSchedule={(data) => scheduleMutation.mutate(data)}
          isLoading={scheduleMutation.isPending}
          result={scheduleMutation.data}
        />
      )}
    </div>
  )
}

function SelectedDayDetail({ day, onClose }) {
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

      {day.orders.length > 0 ? (
        <div className="space-y-3">
          {day.orders.map((order, idx) => (
            <div key={idx} className="bg-gray-50 rounded-lg p-4">
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-medium text-gray-900">{order.itemNo}</div>
                  <div className="text-sm text-gray-500">{order.itemDescription || 'Production Order'}</div>
                </div>
                <div className="text-right">
                  <div className="font-medium text-gray-900">{order.quantity} units</div>
                  <div className="text-sm text-gray-500">Due: {order.dueDate}</div>
                </div>
              </div>
              <div className="mt-2 flex items-center text-sm">
                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  order.status === 'Released' ? 'bg-blue-100 text-blue-800' :
                  order.status === 'Finished' ? 'bg-green-100 text-green-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {order.status}
                </span>
                {order.salesOrderNo && (
                  <span className="ml-2 text-gray-500">SO: {order.salesOrderNo}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="mt-2">No production orders scheduled</p>
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
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">End Date</label>
                <input
                  type="date"
                  value={dateRange.endDate}
                  onChange={(e) => setDateRange({ ...dateRange, endDate: e.target.value })}
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
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
                className="text-sm text-indigo-600 hover:text-indigo-700"
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
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500"
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">Quantity</label>
                      <input
                        type="number"
                        min="1"
                        value={order.quantity}
                        onChange={(e) => updateOrder(index, 'quantity', parseInt(e.target.value) || 1)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500"
                      />
                    </div>
                    <div className="col-span-3">
                      <label className="block text-xs text-gray-500 mb-1">Due Date</label>
                      <input
                        type="date"
                        value={order.dueDate}
                        onChange={(e) => updateOrder(index, 'dueDate', e.target.value)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500"
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">Priority</label>
                      <select
                        value={order.priority}
                        onChange={(e) => updateOrder(index, 'priority', e.target.value)}
                        className="w-full border-gray-300 rounded-md shadow-sm text-sm focus:ring-indigo-500 focus:border-indigo-500"
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
              className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
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
