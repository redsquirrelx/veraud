import { useParams } from "react-router-dom"

export function ProjectDetailPage() {
  const { id } = useParams()

  return (
    <section className="page">
      <h1>Project {id}</h1>
      <p>Details coming in the next HU.</p>
    </section>
  )
}
