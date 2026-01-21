# -*- coding: utf-8 -*-
"""
Azure OpenAI Client Setup
"""

from openai import AzureOpenAI
from settings import (
    AZUREAI_API_KEY,
    endpoint,
    api_version
)

# Azure OpenAI Client initialisieren
client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=AZUREAI_API_KEY,
)
