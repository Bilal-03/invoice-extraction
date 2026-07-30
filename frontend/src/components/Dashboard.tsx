"use client";

import { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { useDropzone } from "react-dropzone";
import { UploadCloud, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { apiClient, DocumentResponse } from "@/lib/api-client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DocumentList } from "./DocumentList";

const DocumentPreview = dynamic(() => import("./DocumentPreview").then((mod) => mod.DocumentPreview), {
  loading: () => <div className="h-[560px] animate-pulse rounded-2xl border border-white/10 bg-white/5" />,
});
const AnalyticsView = dynamic(() => import("./AnalyticsView").then((mod) => mod.AnalyticsView), {
  loading: () => <div className="h-[560px] animate-pulse rounded-2xl border border-white/10 bg-white/5" />,
});

export function Dashboard() {
  const [activeTab, setActiveTab] = useState("upload");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentDoc, setCurrentDoc] = useState<DocumentResponse | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  // Poll for document status
  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    if (currentDoc && ["pending", "preprocessing", "ocr", "extracting", "validating"].includes(currentDoc.status)) {
      interval = setInterval(async () => {
        try {
          const res = await apiClient.get<DocumentResponse>(`/documents/${currentDoc.id}`);
          setCurrentDoc(res.data);
          
          if (["completed", "failed"].includes(res.data.status)) {
            clearInterval(interval);
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 2000);
    }
    
    return () => clearInterval(interval);
  }, [currentDoc]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    
    setIsUploading(true);
    setUploadProgress(10);
    setUploadError(null);
    setUploadMessage(null);
    
    const formData = new FormData();
    acceptedFiles.forEach((file) => formData.append(acceptedFiles.length > 1 ? "files" : "file", file));
    
    try {
      // Fake progress for UX
      const progressInterval = setInterval(() => {
        setUploadProgress(p => Math.min(p + 15, 90));
      }, 300);
      
      const endpoint = acceptedFiles.length > 1 ? "/documents/batch" : "/documents";
      const res = await apiClient.post(endpoint, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      
      clearInterval(progressInterval);
      setUploadProgress(100);
      
      // Immediately fetch the doc to get the initial state
      const first = acceptedFiles.length > 1 ? res.data.documents[0] : res.data;
      const docRes = await apiClient.get(`/documents/${first.document_id}`);
      setCurrentDoc(docRes.data);
      setUploadMessage(
        acceptedFiles.length > 1
          ? `${res.data.accepted} documents accepted for processing.`
          : first.duplicate_of
            ? "This file matched an existing document; opening the original."
            : "Document accepted for processing."
      );
      
      setTimeout(() => {
        setIsUploading(false);
        setActiveTab("preview");
      }, 500);
      
    } catch (error: unknown) {
      console.error("Upload failed", error);
      setIsUploading(false);
      setUploadProgress(0);
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setUploadError(detail || "Upload failed. Check the file type and try again.");
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'image/tiff': ['.tiff', '.tif'],
      'application/pdf': ['.pdf']
    },
    maxSize: 20 * 1024 * 1024, // 20MB
    multiple: true
  });

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full space-y-6">
      <TabsList className="grid h-12 w-full grid-cols-3 max-w-lg rounded-2xl bg-white/8 p-1 backdrop-blur-md border border-white/10">
        <TabsTrigger value="upload" className="rounded-xl">Workspace</TabsTrigger>
        <TabsTrigger value="preview" className="rounded-xl" disabled={!currentDoc}>Review</TabsTrigger>
        <TabsTrigger value="analytics" className="rounded-xl">Insights</TabsTrigger>
      </TabsList>
      
      <TabsContent value="upload" className="space-y-6">
        <Card className="overflow-hidden border-white/15 bg-gradient-to-br from-slate-900/80 via-slate-950/70 to-indigo-950/60 shadow-2xl shadow-indigo-950/30 backdrop-blur-xl">
          <CardHeader className="border-b border-white/10 pb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">New extraction</p>
            <CardTitle className="text-2xl">Turn invoices into review-ready data</CardTitle>
            <CardDescription>
              Drag and drop one or more invoice images or PDFs to start extraction.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div 
              {...getRootProps()} 
              className={`
                border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all duration-300
                flex flex-col items-center justify-center gap-4 min-h-[300px]
                ${isDragActive ? 'border-primary bg-primary/10 scale-[1.02]' : 'border-muted-foreground/30 hover:border-primary/50 hover:bg-white/5'}
                ${isUploading ? 'pointer-events-none opacity-80' : ''}
              `}
            >
              <input {...getInputProps()} />
              
              {isUploading ? (
                <div className="flex flex-col items-center gap-4 w-full max-w-sm">
                  <div className="p-4 bg-primary/20 rounded-full animate-pulse">
                    <Loader2 className="w-10 h-10 text-primary animate-spin" />
                  </div>
                  <h3 className="text-xl font-medium">Uploading Document...</h3>
                  <Progress value={uploadProgress} className="h-2 w-full" />
                </div>
              ) : (
                <>
                  <div className="p-4 bg-primary/10 rounded-full">
                    <UploadCloud className="w-12 h-12 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-xl font-medium mb-1">
                      {isDragActive ? "Drop file here" : "Click or drag file to upload"}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      Supports up to 25 JPG, PNG, TIFF, or PDF files (20MB each)
                    </p>
                  </div>
                  <Button variant="outline" className="mt-4 pointer-events-none bg-background/50 backdrop-blur">
                    Browse Files
                  </Button>
                </>
              )}
            </div>
            {uploadError && (
              <div role="alert" className="mt-4 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                <AlertCircle className="h-4 w-4" /> {uploadError}
              </div>
            )}
            {uploadMessage && (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                <CheckCircle2 className="h-4 w-4" /> {uploadMessage}
              </div>
            )}
          </CardContent>
        </Card>
        
        {/* Recent Documents Table underneath */}
        <DocumentList onSelectDoc={(doc) => {
          setCurrentDoc(doc);
          setActiveTab("preview");
        }} />
      </TabsContent>
      
      <TabsContent value="preview">
        {currentDoc ? (
          <DocumentPreview 
            doc={currentDoc} 
            onFieldUpdated={(updatedDoc) => setCurrentDoc(updatedDoc)} 
          />
        ) : (
          <Card>
            <CardContent className="p-12 text-center text-muted-foreground">
              No document selected. Upload a document first.
            </CardContent>
          </Card>
        )}
      </TabsContent>
      
      <TabsContent value="analytics">
        <AnalyticsView />
      </TabsContent>
    </Tabs>
  );
}
