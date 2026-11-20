import SharedDoorPreview from 'door-renderer'

// Highlight colour stays with the widget. The shared renderer does not know the brand.
export default function DoorPreview(props) {
  return (
    <SharedDoorPreview
      className="odc-door-preview"
      highlightFill="rgba(201, 169, 110, 0.2)"
      highlightStroke="rgba(201, 169, 110, 0.8)"
      {...props}
    />
  )
}
