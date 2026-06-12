import React from 'react'
import { CalendarContainer } from '@presentation/containers/CalendarContainer'

const CalendarPage: React.FC = () => {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
      <CalendarContainer />
    </div>
  )
}

export default CalendarPage
