interface Props {
  title: string
}

export function PageHeader({ title }: Props) {
  return (
    <div className="page-header">
      <h1 className="page-title">{title}</h1>
    </div>
  )
}
