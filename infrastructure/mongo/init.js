db = db.getSiblingDB('cancer_results');
db.createCollection('ml_results', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['evaluation_id', 'patient_id', 'service', 'created_at'],
      properties: {
        evaluation_id: { bsonType: 'string' },
        patient_id:    { bsonType: 'string' },
        service:       { bsonType: 'string' },
        fhir_observation: { bsonType: 'object' },
        created_at:    { bsonType: 'date' }
      }
    }
  }
});
db.createCollection('audit_log');
db.ml_results.createIndex({ evaluation_id: 1 });
db.ml_results.createIndex({ patient_id: 1, created_at: -1 });
db.audit_log.createIndex({ patient_id_hash: 1, timestamp: -1 });
db.audit_log.createIndex({ event_type: 1 });
