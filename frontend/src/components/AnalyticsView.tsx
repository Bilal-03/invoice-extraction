"use client";

import { useEffect, useState } from "react";
import { BarChart3, TrendingUp, AlertTriangle, CheckCircle, FileText, Activity, CircleDollarSign } from "lucide-react";
import { apiClient, AnalyticsSummary } from "@/lib/api-client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// Recharts for visualizations
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
  ,LineChart,
  Line,
  Legend
} from 'recharts';

interface VendorAnalytics {
  vendor_name: string;
  document_count: number;
  total_spend: number;
  average_confidence: number;
  currency: string;
}

interface TrendPoint {
  date: string;
  document_count: number;
  average_confidence: number;
  average_processing_time_ms: number;
}

export function AnalyticsView() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [vendors, setVendors] = useState<VendorAnalytics[]>([]);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true);
      try {
        const [summaryRes, vendorsRes, trendsRes] = await Promise.all([
          apiClient.get<AnalyticsSummary>('/analytics/summary'),
          apiClient.get<{vendors: VendorAnalytics[]}>('/analytics/vendors'),
          apiClient.get<{points: TrendPoint[]}>('/analytics/trends')
        ]);
        
        setSummary(summaryRes.data);
        setVendors(vendorsRes.data.vendors);
        setTrends(trendsRes.data.points);
      } catch (error) {
        console.error("Failed to fetch analytics", error);
      } finally {
        setIsLoading(false);
      }
    };
    
    fetchData();
  }, []);

  if (isLoading || !summary) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          {[1,2,3,4].map(i => <Skeleton key={i} className="h-32 w-full bg-white/5" />)}
        </div>
        <Skeleton className="h-[400px] w-full bg-white/5" />
      </div>
    );
  }

  // Format data for chart
  const chartData = vendors.map(v => ({
    name: v.vendor_name,
    spend: v.total_spend,
    count: v.document_count,
    currency: v.currency,
  }));

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      
      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card className="bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Processed</CardTitle>
            <FileText className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary.total_documents}</div>
            <p className="text-xs text-muted-foreground mt-1">
              +{summary.documents_this_week} this week
            </p>
          </CardContent>
        </Card>

        <Card className="bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Avg VLM Cost</CardTitle>
            <CircleDollarSign className="h-4 w-4 text-cyan-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">${summary.average_cost_usd.toFixed(4)}</div>
            <p className="text-xs text-muted-foreground mt-1">Per completed document</p>
          </CardContent>
        </Card>
        
        <Card className="bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Avg Confidence</CardTitle>
            <Activity className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{(summary.average_confidence * 100).toFixed(1)}%</div>
            <p className="text-xs text-muted-foreground mt-1">
              AI extraction certainty
            </p>
          </CardContent>
        </Card>
        
        <Card className="bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">VLM Fallback Rate</CardTitle>
            <BarChart3 className="h-4 w-4 text-purple-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{(summary.vlm_fallback_rate * 100).toFixed(1)}%</div>
            <p className="text-xs text-muted-foreground mt-1">
              Required deep understanding
            </p>
          </CardContent>
        </Card>
        
        <Card className="bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Processing Errors</CardTitle>
            <AlertTriangle className="h-4 w-4 text-red-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary.failed_documents}</div>
            <p className="text-xs text-muted-foreground mt-1">
              Failed pipeline executions
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Charts section */}
      <Card className="bg-white/5 border-white/10 backdrop-blur-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><TrendingUp className="h-4 w-4 text-blue-400" /> Processing trend</CardTitle>
          <CardDescription>Daily volume, confidence, and latency over the last 30 days</CardDescription>
        </CardHeader>
        <CardContent className="h-[280px]">
          {trends.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trends} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#ffffff20" />
                <XAxis dataKey="date" stroke="#ffffff50" fontSize={11} tickLine={false} />
                <YAxis yAxisId="count" stroke="#ffffff50" fontSize={11} tickLine={false} allowDecimals={false} />
                <YAxis yAxisId="confidence" orientation="right" domain={[0, 1]} stroke="#ffffff50" fontSize={11} tickFormatter={(value) => `${Math.round(value * 100)}%`} />
                <Tooltip contentStyle={{ backgroundColor: '#111', borderColor: '#333', borderRadius: '8px' }} />
                <Legend />
                <Line yAxisId="count" type="monotone" dataKey="document_count" name="Documents" stroke="#60a5fa" strokeWidth={2} />
                <Line yAxisId="confidence" type="monotone" dataKey="average_confidence" name="Confidence" stroke="#34d399" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : <div className="flex h-full items-center justify-center text-muted-foreground">Trend data will appear after documents are processed.</div>}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-7">
        <Card className="md:col-span-4 bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader>
            <CardTitle>Spend by Vendor</CardTitle>
            <CardDescription>Top vendors by total invoice value, separated by currency</CardDescription>
          </CardHeader>
          <CardContent className="h-[350px]">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#ffffff20" />
                  <XAxis 
                    dataKey="name" 
                    stroke="#ffffff50" 
                    fontSize={12} 
                    tickLine={false}
                    axisLine={false}
                    angle={-45}
                    textAnchor="end"
                    height={60}
                  />
                  <YAxis 
                    stroke="#ffffff50" 
                    fontSize={12} 
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(value) => Number(value).toLocaleString()}
                  />
                  <Tooltip 
                    cursor={{fill: '#ffffff10'}}
                    contentStyle={{ backgroundColor: '#111', borderColor: '#333', borderRadius: '8px' }}
                    itemStyle={{ color: '#fff' }}
                  />
                  <Bar dataKey="spend" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={`hsl(${(index * 45) % 360}, 70%, 60%)`} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground">
                Not enough data yet.
              </div>
            )}
          </CardContent>
        </Card>
        
        <Card className="md:col-span-3 bg-white/5 border-white/10 backdrop-blur-md">
          <CardHeader>
            <CardTitle>Top Vendors Summary</CardTitle>
            <CardDescription>Metrics grouped by vendor and currency</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {vendors.slice(0, 5).map((vendor, i) => (
                <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-black/20 border border-white/5">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold">
                      {vendor.vendor_name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium leading-none">{vendor.vendor_name}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {vendor.document_count} invoices
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium">{vendor.currency} {vendor.total_spend.toLocaleString()}</p>
                    <p className="text-xs text-muted-foreground mt-1 flex items-center justify-end gap-1">
                      {vendor.average_confidence > 0.8 ? (
                        <CheckCircle className="w-3 h-3 text-emerald-500" />
                      ) : (
                        <AlertTriangle className="w-3 h-3 text-amber-500" />
                      )}
                      {(vendor.average_confidence * 100).toFixed(0)}% conf
                    </p>
                  </div>
                </div>
              ))}
              
              {vendors.length === 0 && (
                <div className="text-center py-8 text-muted-foreground">
                  No vendor data available
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
