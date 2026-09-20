import { defineStore } from "pinia";
import { ref } from "vue";

import {
  deleteDocument,
  fetchDocuments,
  uploadDocument,
  type Document,
} from "@/api/document";

export const useDocumentStore = defineStore("document", () => {
  const documents = ref<Document[]>([]);
  const loading = ref(false);
  const uploadProgress = ref(0);

  async function loadDocuments() {
    loading.value = true;
    try {
      const res = await fetchDocuments();
      documents.value = res.data?.items || [];
    } catch (err) {
      documents.value = [];
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function upload(file: File) {
    uploadProgress.value = 0;
    try {
      const res = await uploadDocument(file);
      documents.value.unshift(res.data);
      uploadProgress.value = 100;
      return res.data;
    } catch (err) {
      uploadProgress.value = 0;
      throw err;
    }
  }

  async function remove(documentId: number) {
    await deleteDocument(documentId);
    documents.value = documents.value.filter((d) => d.id !== documentId);
  }

  return {
    documents,
    loading,
    uploadProgress,
    loadDocuments,
    upload,
    remove,
  };
});