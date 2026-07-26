import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { TraceList } from './pages/TraceList'
import { TraceDetail } from './pages/TraceDetail'
import { IssueBoard } from './pages/IssueBoard'
import { IssueDetail } from './pages/IssueDetail'
import { Calibration } from './pages/Calibration'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<TraceList />} />
          <Route path="traces/:traceId" element={<TraceDetail />} />
          <Route path="issues" element={<IssueBoard />} />
          <Route path="issues/:issueId" element={<IssueDetail />} />
          <Route path="calibrate" element={<Calibration />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
