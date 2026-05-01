import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import CaseDetailPage from './pages/CaseDetail'
import QueuePage from './pages/Queue'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<QueuePage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
      </Routes>
    </Layout>
  )
}

export default App
