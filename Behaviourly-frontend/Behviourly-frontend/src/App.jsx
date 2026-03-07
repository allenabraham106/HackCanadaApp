import Camera from './Camera'

function App() {
  return (
    <div>
      <Camera onRecordingComplete={(blob, url) => {
        console.log("Recording done!", url)
      }} />
    </div>
  )
}

export default App