import api from "./index";

export interface Document {
  id: number;
  filename: string;
  chunk_count?: number;
  [key: string]: unknown;
}

export function fetchDocuments(): Promise<{ data: { items: Document[] } }> {
  return api.get("/documents");
}

export function uploadDocument(
  file: File
): Promise<{ data: Document }> {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export function deleteDocument(
  documentId: number
): Promise<{ data: { message?: string } }> {
  return api.delete(`/documents/${documentId}`);
}