"use client";

import { useCallback, useEffect, useState } from "react";
import { format } from "date-fns";
import { FileText, Loader2, Search, ArrowRight, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";

import { apiClient, DocumentResponse } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface DocumentListProps {
  onSelectDoc: (doc: DocumentResponse) => void;
}

export function DocumentList({ onSelectDoc }: DocumentListProps) {
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await apiClient.get('/documents', {
        params: {
          vendor: searchTerm || undefined,
          status: statusFilter || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        }
      });
      setDocuments(res.data.documents);
    } catch (error) {
      console.error("Failed to fetch documents", error);
    } finally {
      setIsLoading(false);
    }
  }, [searchTerm, statusFilter, dateFrom, dateTo]);

  useEffect(() => {
    const debounce = window.setTimeout(fetchDocuments, 250);
    return () => window.clearTimeout(debounce);
  }, [fetchDocuments]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <Badge variant="default" className="bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20"><CheckCircle2 className="w-3 h-3 mr-1"/> Completed</Badge>;
      case "failed":
        return <Badge variant="destructive" className="bg-red-500/10 text-red-500 hover:bg-red-500/20"><AlertCircle className="w-3 h-3 mr-1"/> Failed</Badge>;
      case "pending":
      case "preprocessing":
      case "ocr":
      case "extracting":
      case "validating":
        return <Badge variant="secondary" className="bg-blue-500/10 text-blue-500 hover:bg-blue-500/20"><Loader2 className="w-3 h-3 mr-1 animate-spin"/> {status}</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  return (
    <Card className="border-white/10 bg-black/40 backdrop-blur-xl">
      <CardHeader className="flex flex-col gap-4 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <CardTitle className="text-xl font-medium flex items-center gap-2">
          <FileText className="w-5 h-5 text-muted-foreground" />
          Recent Documents
        </CardTitle>
        <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
          <div className="relative min-w-48 flex-1 lg:w-56 lg:flex-none">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search vendor"
              className="pl-8 bg-white/5 border-white/10"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="h-8 rounded-lg border border-white/10 bg-black/40 px-3 text-sm"
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="pending">Pending</option>
            <option value="preprocessing">Preprocessing</option>
            <option value="ocr">OCR</option>
            <option value="extracting">Extracting</option>
            <option value="validating">Validating</option>
            <option value="failed">Failed</option>
          </select>
          <Input aria-label="From date" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="w-36 bg-white/5" />
          <Input aria-label="To date" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="w-36 bg-white/5" />
          <Button variant="ghost" size="icon" onClick={fetchDocuments} aria-label="Refresh documents">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center p-8 text-muted-foreground border border-dashed border-white/10 rounded-lg bg-white/5">
            No documents found.
          </div>
        ) : (
          <div className="rounded-md border border-white/10 overflow-hidden">
            <Table>
              <TableHeader className="bg-white/5">
                <TableRow className="border-white/10 hover:bg-transparent">
                  <TableHead>Filename</TableHead>
                  <TableHead>Vendor</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id} className="border-white/10 hover:bg-white/5 cursor-pointer transition-colors" onClick={() => onSelectDoc(doc)}>
                    <TableCell className="font-medium max-w-[200px] truncate" title={doc.filename}>
                      {doc.filename}
                    </TableCell>
                    <TableCell>
                      {doc.extraction?.vendor?.name?.value || <span className="text-muted-foreground italic">Unknown</span>}
                    </TableCell>
                    <TableCell>
                      {doc.extraction?.grand_total ? (
                        `${doc.extraction.currency || '₹'} ${Number(doc.extraction.grand_total).toFixed(2)}`
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>{getStatusBadge(doc.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {format(new Date(doc.created_at), "MMM d, yyyy HH:mm")}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary">
                        <ArrowRight className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
