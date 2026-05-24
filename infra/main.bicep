// =============================================================================
// Infrastructure as Code — Azure resources for Document Extraction Pipeline
// =============================================================================
// Deploy with: az deployment group create -g <resource-group> -f main.bicep
//
// Parameters:
//   suffix     — unique suffix to avoid naming collisions (e.g., "prod", "dev01")
//   location   — Azure region (default: eastus)
// =============================================================================

@description('Unique suffix for resource names (e.g., prod, dev01)')
param suffix string

@description('Azure region for all resources')
param location string = resourceGroup().location

// =============================================================================
// Azure Cosmos DB — Serverless (pay-per-request, scales from zero)
// =============================================================================
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-docextract-${suffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    // Security: disable key-based auth in production (use RBAC only)
    disableLocalAuth: false
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'documents'
  properties: {
    resource: {
      id: 'documents'
    }
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'extractions'
  properties: {
    resource: {
      id: 'extractions'
      partitionKey: {
        paths: ['/partition_key']
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [
          { path: '/source_hash/?' }
          { path: '/partition_key/?' }
          { path: '/created_at/?' }
        ]
        excludedPaths: [
          { path: '/*' }
        ]
      }
    }
  }
}

// =============================================================================
// Azure Blob Storage — PDF staging + extraction results
// =============================================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stdocextract${suffix}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource stagingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'pdf-staging'
}

resource resultsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'extraction-results'
}

// =============================================================================
// Azure Content Understanding (S0) — Primary deterministic extractor
// =============================================================================
resource contentUnderstanding 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: 'cu-docextract-${suffix}'
  location: location
  kind: 'ContentUnderstanding'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'cu-docextract-${suffix}'
    publicNetworkAccess: 'Enabled'
  }
}

// =============================================================================
// Azure Service Bus (Basic) — Event-driven queue integration
// =============================================================================
resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: 'sb-docextract-${suffix}'
  location: location
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
}

resource processingQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBus
  name: 'document-processing'
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 3
    defaultMessageTimeToLive: 'P7D'
  }
}

resource reviewQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBus
  name: 'human-review'
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 5
    defaultMessageTimeToLive: 'P14D'
  }
}

// =============================================================================
// Application Insights — Observability via OpenTelemetry
// =============================================================================
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'ai-docextract-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
  }
}

// =============================================================================
// Outputs — used by application configuration
// =============================================================================
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output cosmosAccountName string = cosmosAccount.name
output storageAccountName string = storageAccount.name
output cuEndpoint string = contentUnderstanding.properties.endpoint
output cuAccountName string = contentUnderstanding.name
output serviceBusNamespace string = serviceBus.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
