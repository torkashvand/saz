import { Button } from '@/components/ui/button';
import { FileQuestion } from 'lucide-react';
import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-8">
        <div className="flex flex-col items-center text-center">
          <div className="rounded-full bg-slate-100 p-3 mb-4">
            <FileQuestion className="h-8 w-8 text-slate-600" />
          </div>

          <h1 className="text-2xl font-bold text-gray-900 mb-2">Page Not Found</h1>

          <p className="text-gray-600 mb-6">
            The page you&apos;re looking for doesn&apos;t exist or has been moved.
          </p>

          <Link href="/" className="w-full">
            <Button className="w-full">Back to Home</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
