import os
from typing import List, Dict, Any, Union
import torch
from FlagEmbedding import BGEM3FlagModel

class VectorizationService:
    def __init__(self, use_gpu: bool = True, batch_size: int = 12):
        """
        Initializes the BGE-M3 Encoder.
        
        :param use_gpu: If True, attempts to use CUDA/GPU for acceleration.
        :param batch_size: Default batch size for processing large lists of documents.
        """
        self.batch_size = batch_size
        
        # Determine if GPU is available and requested
        device_available = torch.cuda.is_available()
        self.use_fp16 = use_gpu and device_available
        
        print(f"Initializing BGE-M3 Model...")
        print(f"GPU Available: {device_available} | Utilizing FP16 (GPU): {self.use_fp16}")
        
        # Load the model. It automatically pulls from Hugging Face if not cached locally.
        self.model = BGEM3FlagModel(
            'BAAI/bge-m3', 
            use_fp16=self.use_fp16
        )
        print("BGE-M3 Model loaded successfully.")

    def vectorize(
        self, 
        documents: Union[str, List[str]], 
        return_dense: bool = True, 
        return_sparse: bool = False, 
        return_colbert: bool = False
    ) -> Dict[str, Any]:
        """
        Vectorizes a document or a list of documents into vectors.
        
        :param documents: A single string or a list of strings to vectorize.
        :param return_dense: Returns standard 1024-dimension embeddings.
        :param return_sparse: Returns lexical token-weight mappings (great for hybrid search).
        :param return_colbert: Returns multi-vector token embeddings (great for late interaction).
        :return: A dictionary containing the requested vector formats.
        """
        # Ensure input is a list even if a single string is passed
        if isinstance(documents, str):
            documents = [documents]
            
        if not documents:
            return {"dense": [], "sparse": [], "colbert": []}

        # Run the BGE-M3 underlying encoding mechanism
        encoded_output = self.model.encode(
            documents,
            batch_size=self.batch_size,
            return_dense=return_dense,
            return_sparse=return_sparse,
            return_colbert_vecs=return_colbert
        )
        
        result = {}
        
        # Format Dense vectors as standard Python lists
        if return_dense:
            result["dense"] = encoded_output["dense_vecs"].tolist()
            
        # Format Sparse vectors (returns dictionaries of {token_id: weight})
        if return_sparse:
            result["sparse"] = encoded_output["lexical_weights"]
            
        # Format ColBERT vectors (converts multi-vector arrays to nested lists)
        if return_colbert:
            result["colbert"] = [vec.tolist() for vec in encoded_output["colbert_vecs"]]
            
        return result