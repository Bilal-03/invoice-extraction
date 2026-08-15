import { FileUp, Loader2, UploadCloud } from "lucide-react";
import type { DropzoneState } from "react-dropzone";

export function InvoiceUploader({ dropzone, uploading }: { dropzone: DropzoneState; uploading: boolean }) {
  return (
    <div {...dropzone.getRootProps()} className={`dropzone ${dropzone.isDragActive ? "dragging" : ""}`}>
      <input {...dropzone.getInputProps()} />
      {uploading ? <><Loader2 size={31} className="spin" /><h2>Adding documents to the queue…</h2></> : <><UploadCloud size={34} /><h2>Drop invoices here</h2><p>or click to browse · PDF, JPG, JPEG, PNG, TIFF · up to 20 MB each</p><button type="button" className="primary-button"><FileUp size={15} /> Browse files</button></>}
      <small>Multiple invoices supported · deterministic OCR first · Ollama is optional</small>
    </div>
  );
}
